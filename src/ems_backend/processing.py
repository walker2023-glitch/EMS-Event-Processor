"""Bounded, literal-only workbook adapter; existing desktop modules are unchanged."""

import hashlib
import io
import json
import re
import zipfile
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from zoneinfo import ZoneInfo

from ems_event_processor.exporter import export_workbooks
from ems_event_processor.models import Record
from ems_event_processor.parser import ReportParser
from ems_event_processor.reader import InputError, read_rows
from ems_event_processor.summary import summarize

from .config import Settings
from .gateway import JSON, BackendError

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
XLS = "application/vnd.ms-excel"


def normalize(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def serial(value: Any) -> Any:
    if isinstance(value, (date, time, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(type(value).__name__)


def json_value(value: Any) -> Any:
    return json.loads(json.dumps(value, default=serial))


def validate(content: bytes, filename: str, mime: str, settings: Settings) -> str:
    extension = Path(filename).suffix.lower()
    if extension not in {".xls", ".xlsx"}:
        raise BackendError(422, "unsupported_file", "Choose a .xls or .xlsx workbook.")
    if not content or len(content) > settings.max_upload_bytes:
        raise BackendError(413, "upload_size", "The workbook is empty or exceeds the upload limit.")
    if mime not in {XLS, XLSX, "application/octet-stream"}:
        raise BackendError(422, "unsupported_mime", "The upload must be an Excel workbook.")
    try:
        if extension == ".xls":
            if not content.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
                raise ValueError("Not an OLE workbook")
        else:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                entries = archive.infolist()
                if (
                    len(entries) > 3000
                    or sum(x.file_size for x in entries) > settings.max_uncompressed_bytes
                ):
                    raise ValueError("Workbook expansion limit")
                names = archive.namelist()
                if "xl/workbook.xml" not in names or "[Content_Types].xml" not in names:
                    raise ValueError("Not an XLSX workbook")
                if any(
                    "vbaproject" in x.casefold()
                    or x.endswith("/") is False
                    and ".." in x.split("/")
                    for x in names
                ):
                    raise ValueError("Embedded VBA or invalid path")
    except (ValueError, zipfile.BadZipFile):
        raise BackendError(
            422, "invalid_workbook", "The file is not a supported readable Excel workbook."
        ) from None
    return extension


def calendar_source(source: JSON, timezone: str) -> list[JSON]:
    day = source.get("event_date")
    start, end = source.get("start_time"), source.get("end_time")
    begins = (
        datetime.combine(
            date.fromisoformat(day),
            time.fromisoformat(start) if start else time(),
            ZoneInfo(timezone),
        )
        if day
        else None
    )
    ends = (
        datetime.combine(date.fromisoformat(day), time.fromisoformat(end), ZoneInfo(timezone))
        if day and start and end
        else None
    )
    if ends and begins and ends < begins:
        ends = None  # An overnight end is not inferred from an ambiguous source.
    if begins and not start:
        ends = begins + timedelta(days=1)
    return [
        {
            "item_type": "event",
            "title": source.get("event_name") or "Unnamed event",
            "start_at": begins.isoformat() if begins else None,
            "end_at": ends.isoformat() if ends else None,
            "all_day": not bool(start),
            "location": source.get("location"),
            "description": "Imported EMS event. Review source issues before planning.",
        }
    ]


def candidate(row: Record, requests: list[Record], timezone: str) -> JSON:
    mapping = {
        "source_request_id": "Book ID",
        "source_reservation_id": "Reservation ID",
        "event_name": "Event Name",
        "event_date": "Event Date",
        "start_time": "Event Start",
        "end_time": "Event End",
        "location": "Location",
        "source_sheet": "Source Sheet",
        "source_row": "Source Row",
        "source_page": "Source Page",
        "original_request_text": "Original Source Text",
        "data_quality_status": "Data Quality Status",
    }
    source = json_value({key: row.get(value) for key, value in mapping.items()})
    source["contact_or_group"] = str(row.get("Primary Contact") or row.get("Group") or "")
    # Stable identifiers are scoped by occurrence date so recurring bookings stay separate.
    keys = []
    day = source.get("event_date")
    if day:
        for prefix, field in (
            ("request", "source_request_id"),
            ("reservation", "source_reservation_id"),
        ):
            if source.get(field):
                keys.append(
                    json.dumps([prefix, normalize(source[field]), day], separators=(",", ":"))
                )
        fallback = [
            normalize(source.get(x)) for x in ("event_name", "location", "contact_or_group")
        ]
        if all(fallback):
            keys.append(
                json.dumps(
                    ["normalized", *fallback, day, source.get("start_time")], separators=(",", ":")
                )
            )
    resource_rows = [r for r in requests if r.get("Event ID") == row.get("Event ID")]
    resources = json_value(
        [
            {
                "resource_description": r.get("Equipment Description"),
                "resource_category": r.get("Equipment Category"),
                "quantity": r.get("Quantity"),
                "source_text": r.get("Original Request Text"),
                "source_data": r,
            }
            for r in resource_rows
        ]
    )
    fingerprint_source = {
        k: v for k, v in source.items() if k not in {"source_sheet", "source_row", "source_page"}
    }
    fingerprint_resources = [
        {k: r[k] for k in ("resource_description", "resource_category", "quantity", "source_text")}
        for r in resources
    ]
    digest = hashlib.sha256(
        json.dumps([fingerprint_source, fingerprint_resources], sort_keys=True).encode()
    ).hexdigest()
    return {
        "candidate_id": str(row["Event ID"]),
        "source": source,
        "match_keys": keys,
        "fingerprint": digest,
        "resources": resources,
        "calendar": calendar_source(source, timezone),
    }


def process(content: bytes, extension: str, settings: Settings) -> JSON:
    try:
        with TemporaryDirectory(prefix="ems-api-") as folder:
            source, output = Path(folder) / ("source" + extension), Path(folder) / "organized.xlsx"
            source.write_bytes(content)
            before = (hashlib.sha256(content).digest(), source.stat().st_mtime_ns)
            rows = []
            for row in read_rows(source):
                rows.append(row)
                if len(rows) > settings.max_rows or len(row.text) > 500_000:
                    raise BackendError(
                        413,
                        "workbook_limit",
                        "The workbook exceeds this deployment's processing limit.",
                    )
            parsed = ReportParser().parse(rows)
            if len(parsed.events) > settings.max_candidates:
                raise BackendError(
                    413, "event_limit", "The workbook contains too many events for this deployment."
                )
            export_workbooks(
                output,
                output.with_name("organized_issues.xlsx"),
                parsed,
                summarize(parsed.requests),
            )
            if before != (hashlib.sha256(source.read_bytes()).digest(), source.stat().st_mtime_ns):
                raise RuntimeError("Source preservation failed")
            return {
                "candidates": [
                    candidate(row, parsed.requests, settings.calendar_timezone)
                    for row in parsed.events
                ],
                "issues": json_value(parsed.issues),
                "exports": [
                    ("organized_workbook", output.read_bytes()),
                    *(
                        [
                            (
                                "issues_workbook",
                                output.with_name("organized_issues.xlsx").read_bytes(),
                            )
                        ]
                        if parsed.issues
                        else []
                    ),
                ],
                "counts": {
                    "events": len(parsed.events),
                    "resource_requests": len(parsed.requests),
                    "summary_rows": len(summarize(parsed.requests)),
                    "issues": len(parsed.issues),
                },
            }
    except BackendError:
        raise
    except (InputError, ValueError, OSError, KeyError, zipfile.BadZipFile):
        raise BackendError(
            422,
            "invalid_workbook",
            "The workbook could not be read. Check the format and try again.",
        ) from None


def safe_filename(filename: str | None) -> str:
    return re.sub(
        r"[^A-Za-z0-9._ -]", "_", (filename or "workbook").replace("\\", "/").split("/")[-1]
    )[:180]
