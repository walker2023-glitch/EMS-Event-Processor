"""Label-driven report state machine. Unknown text always becomes a review issue."""

import re
from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from uuid import NAMESPACE_URL, uuid5

from .models import ParsedWorkbook, Record, SourceRow, Value
from .normalize import parse_date, parse_time, quantity, split_request, text
from .setup_worksheet import SetupWorksheetLayout

ALIASES = {
    "event": "Event Name",
    "event name": "Event Name",
    "booking": "Event Name",
    "event date": "Event Date",
    "date": "Event Date",
    "reservation start": "Reservation Start",
    "reservation end": "Reservation End",
    "event start": "Event Start",
    "event end": "Event End",
    "start time": "Event Start",
    "end time": "Event End",
    "event time": "Event Time",
    "reservation time": "Reservation Time",
    "location": "Location",
    "room": "Location",
    "room name": "Location",
    "setup/event type": "Setup/Event Type",
    "setup type": "Setup/Event Type",
    "event type": "Setup/Event Type",
    "group": "Group",
    "organization": "Group",
    "status": "Status",
    "primary contact": "Primary Contact",
    "contact": "Primary Contact",
    "additional contacts": "Additional Contacts",
    "contacts": "Additional Contacts",
    "email": "Additional Contacts",
    "phone": "Additional Contacts",
    "reservation id": "Reservation ID",
    "reservation #": "Reservation ID",
    "reservation number": "Reservation ID",
    "parent reservation id": "Parent Reservation ID",
    "parent reservation #": "Parent Reservation ID",
    "book id": "Book ID",
    "book #": "Book ID",
    "booking id": "Book ID",
    "event notes": "Event Notes",
    "notes": "Notes",
    "note": "Notes",
    "request notes": "Request Notes",
    "quantity": "Quantity",
    "qty": "Quantity",
    "description": "Equipment Description",
    "equipment description": "Equipment Description",
    "item": "Equipment Description",
    "equipment category": "Equipment Category",
    "category": "Equipment Category",
    "action": "Action or Section",
    "section": "Action or Section",
}
_LABEL_PATTERN = "|".join(re.escape(k) for k in sorted(ALIASES, key=len, reverse=True))
INLINE = re.compile(rf"(?<!\w)({_LABEL_PATTERN})\s*:\s*", re.I)
SECTIONS = {
    "equipment",
    "equipment requests",
    "service requests",
    "services",
    "resources",
    "setup",
    "set up",
    "takedown",
    "tear down",
}


def stable_id(kind: str, *parts: object) -> str:
    return kind + "-" + uuid5(NAMESPACE_URL, repr(parts)).hex[:20]


def label(value: Value) -> str | None:
    return ALIASES.get(text(value).rstrip(":").strip().casefold())


def fields_in(cells: tuple[Value, ...]) -> Record:
    result: Record = {}
    active: str | None = None
    unused: list[str] = []
    for value in cells:
        if value is None or value == "":
            continue
        matches = list(INLINE.finditer(text(value)))
        if matches and matches[0].start() == 0:
            for i, match in enumerate(matches):
                key = ALIASES[match.group(1).casefold()]
                end = matches[i + 1].start() if i + 1 < len(matches) else len(text(value))
                chunk = text(value)[match.end() : end].strip()
                result[key] = chunk
                active = key if not chunk else None
        elif (found_key := label(value)) is not None:
            key = found_key
            result.setdefault(key, "")
            active = key
        elif active:
            result[active] = (
                value if not result[active] else text(result[active]) + " | " + text(value)
            )
        else:
            unused.append(text(value))
    if result and unused:
        result["_Unparsed Text"] = " | ".join(unused)
    return result


def header_map(cells: tuple[Value, ...]) -> dict[int, str] | None:
    mapped = {i: key for i, value in enumerate(cells) if (key := label(value))}
    nonempty = sum(bool(text(v)) for v in cells)
    if len(mapped) < 2 or len(mapped) != nonempty:
        return None
    if "Event Name" in mapped.values() or "Equipment Description" in mapped.values():
        return mapped
    return None


class ReportParser:
    def __init__(self) -> None:
        self.result = ParsedWorkbook()
        self.event: Record | None = None
        self.event_source: SourceRow | None = None
        self.raw: list[str] = []
        self.current_date: date | None = None
        self.date_original: Value = None
        self.section = ""
        self.category = ""
        self.request: Record | None = None
        self.table: dict[int, str] | None = None
        self.sheet = ""
        self.page: int | None = None
        self.continuation = False
        self.note_target = ""
        self.seen_content = False
        self.setup_layout = SetupWorksheetLayout()

    def issue(
        self, row: SourceRow, kind: str, description: str, original: str | None = None
    ) -> None:
        event = self.event or {}
        self.result.issues.append(
            {
                "Issue ID": stable_id(
                    "ISS", row.file, row.sheet, row.number, kind, len(self.result.issues)
                ),
                "Issue Type": kind,
                "Severity": "Warning",
                "Description": description,
                "Original Text": row.text if original is None else original,
                "Related Event ID": event.get("Event ID"),
                "Reservation ID": event.get("Reservation ID"),
                "Book ID": event.get("Book ID"),
                **row.provenance(),
                "Suggested Review Action": "Compare with the source and correct manually.",
            }
        )
        if self.event:
            self.event["Data Quality Status"] = "Review required"

    def finish(self) -> None:
        if self.event is None or self.event_source is None:
            return
        event = self.event
        for name in ("Event Name", "Event Date", "Location"):
            if not event.get(name):
                self.issue(self.event_source, "Missing event value", f"Missing {name}.")
        if not any(event.get(k) for k in ("Reservation ID", "Parent Reservation ID", "Book ID")):
            self.issue(
                self.event_source, "Missing identifiers", "No source reservation or book ID."
            )
        event["Original Source Text"] = "\n".join(self.raw)
        for request in self.result.requests:
            if request["Event ID"] == event["Event ID"]:
                request["Event Date"] = event.get("Event Date")
                request["Location"] = event.get("Location")
        for issue in self.result.issues:
            if issue.get("Related Event ID") == event["Event ID"]:
                issue["Reservation ID"] = event.get("Reservation ID")
                issue["Book ID"] = event.get("Book ID")
        self.result.events.append(event)
        self.event = None
        self.event_source = None
        self.raw = []
        self.section = self.category = self.note_target = ""
        self.request = None

    def start(self, row: SourceRow) -> None:
        self.event = {
            **row.provenance(),
            "Event ID": stable_id("EVT", row.file, row.sheet, row.number),
            "Event Date": self.current_date,
            "Data Quality Status": "OK",
        }
        if self.date_original is not None:
            self.raw.append("Date context: " + text(self.date_original))
        self.event_source = row

    def set_field(self, key: str, value: Value, row: SourceRow) -> None:
        assert self.event is not None
        if isinstance(value, str):
            value = value.strip()
        if key == "Event Date":
            parsed_date = parse_date(value)
            if parsed_date is None:
                self.issue(row, "Invalid date", "Date is not an unambiguous supported date.")
            self.event[key] = parsed_date or value
        elif key in {"Event Time", "Reservation Time"}:
            parts = re.split(r"\s+[-–—]\s+", text(value))
            prefix = key.split()[0]
            if len(parts) == 2:
                self.set_field(prefix + " Start", parts[0], row)
                self.set_field(prefix + " End", parts[1], row)
            else:
                self.issue(
                    row, "Invalid time range", "Time range preserved without interpretation."
                )
        elif key.endswith((" Start", " End")):
            parsed_time = parse_time(value)
            if parsed_time is None:
                self.issue(row, "Invalid time", f"Cannot parse {key}; original value retained.")
            self.event[key] = parsed_time or value
        elif key in {"Notes", "Event Notes", "Request Notes"}:
            if key != "Event Notes" and self.request is not None and self.section:
                self.append(self.request, "Request Notes", value)
                self.note_target = "request"
            else:
                self.append(self.event, "Event Notes", value)
                self.note_target = "event"
        elif key in {"Primary Contact", "Additional Contacts"}:
            if key == "Primary Contact" and self.event.get(key) and self.event[key] != value:
                key = "Additional Contacts"
            self.append(self.event, key, value)
        else:
            old = self.event.get(key)
            if old and old != value:
                self.issue(row, "Conflicting value", f"Multiple values for {key}; all preserved.")
                self.event[key] = text(old) + " | " + text(value)
            else:
                self.event[key] = value

    @staticmethod
    def append(record: Record, key: str, value: Value) -> None:
        old = text(record.get(key))
        record[key] = old + "\n" + text(value) if old else value

    def add_request(self, row: SourceRow, fields: Record) -> None:
        if self.event is None:
            self.issue(row, "Orphan equipment", "Equipment cannot be linked to an event.")
            return
        description = text(fields.get("Equipment Description"))
        if "Quantity" in fields:
            count = quantity(fields["Quantity"])
        else:
            description, count = split_request(description)
        request: Record = {
            **row.provenance(),
            "Equipment Request ID": stable_id("REQ", self.event["Event ID"], row.sheet, row.number),
            "Event ID": self.event["Event ID"],
            "Equipment Description": description,
            "Quantity": count,
            "Original Request Text": row.text,
            "Request Notes": fields.get("Request Notes", fields.get("Notes", "")),
            "Action or Section": fields.get("Action or Section", self.section),
            "Equipment Category": fields.get("Equipment Category", self.category),
            "Data Quality Status": "OK",
        }
        self.result.requests.append(request)
        self.request = request
        self.note_target = ""
        if count is None or not description:
            request["Data Quality Status"] = "Review required"
            self.issue(
                row,
                "Ambiguous equipment",
                "Quantity or description is missing/ambiguous; "
                "excluded from totals until both are clear.",
            )
        if row.errors:
            request["Data Quality Status"] = "Review required"
            request["Quantity"] = None

    def consume(self, row: SourceRow) -> None:
        if row.sheet != self.sheet:
            self.finish()
            self.current_date = None
            self.date_original = None
            self.table = None
            self.page = None
            self.sheet = row.sheet
        if row.page is not None and row.page != self.page:
            self.continuation = self.event is not None
            self.page = row.page
        row = SourceRow(row.file, row.sheet, row.number, self.page, row.cells, row.errors)
        if self.setup_layout.consume(self, row):
            return
        values = [v for v in row.cells if text(v)]
        if not values:
            return  # Blank layout rows never detach equipment or notes.
        single = text(values[0]) if len(values) == 1 else ""
        page_match = re.fullmatch(r"Page\s+(\d+)(?:\s+of\s+\d+)?", single, re.I)
        if page_match:
            self.page = int(page_match.group(1))
            self.continuation = self.event is not None
            return
        if single.casefold() in {
            "setup worksheet",
            "byu-idaho",
            "setup worksheet report",
            "brigham young university - idaho",
        }:
            self.continuation = self.event is not None
            return
        self.seen_content = True
        if found_header := header_map(row.cells):
            self.table = found_header
            self.continuation = self.event is not None
            return
        if single and (date_value := parse_date(values[0])):
            if self.event and self.event.get("Event Date") != date_value:
                self.finish()
            self.current_date, self.date_original = date_value, values[0]
            self.table = None
            return
        if single.rstrip(":").casefold() in SECTIONS:
            self.section = single.rstrip(":")
            self.table = None
            self.note_target = ""
            return
        fields = fields_in(row.cells)
        table_row = False
        # Labels take priority over an active equipment table for metadata/notes.
        if self.table and not label(values[0]) and not INLINE.match(text(values[0])):
            fields = {key: row.cells[i] for i, key in self.table.items() if i < len(row.cells)}
            table_row = True
            extra = [v for i, v in enumerate(row.cells) if i not in self.table and text(v)]
            if extra:
                self.issue(row, "Unmapped columns", "Extra table columns retained in source text.")
        if not fields and single:
            section_match = re.match(
                r"(Equipment|Equipment Requests|Service Requests):\s*(.+)", single, re.I
            )
            if section_match:
                self.section = section_match.group(1)
                fields = {"Equipment Description": section_match.group(2)}
        if fields:
            unparsed = fields.pop("_Unparsed Text", None)
            has_event = any(
                key in fields
                for key in ("Event Name", "Reservation ID", "Book ID", "Parent Reservation ID")
            )
            new_event = False
            if self.event and has_event:
                for key in ("Event Name", "Reservation ID", "Book ID", "Parent Reservation ID"):
                    value = fields.get(key)
                    if value and self.event.get(key):
                        if value != self.event[key] or (
                            key == "Event Name" and not self.continuation
                        ):
                            new_event = True
                if table_row and "Event Name" in fields:
                    new_event = True
            if self.event and "Event Date" in fields:
                if self.event.get("Event Date") and self.event.get("Event Date") != parse_date(
                    fields["Event Date"]
                ):
                    new_event = True
            if new_event:
                self.finish()
            if self.event is None and has_event:
                self.start(row)
            if self.event is None and set(fields) == {"Event Date"}:
                self.current_date = parse_date(fields["Event Date"])
                self.date_original = fields["Event Date"]
                if self.current_date is None:
                    self.issue(row, "Invalid date", "Date context cannot be parsed.")
                return
            if self.event:
                self.raw.append(row.text)
            if unparsed:
                self.issue(row, "Unparsed text", "Unlabelled metadata text retained for review.")
            equipment_fields = {"Equipment Description", "Quantity"}
            if equipment_fields.intersection(fields):
                if self.event:
                    for key, value in fields.items():
                        if key not in equipment_fields | {
                            "Notes",
                            "Request Notes",
                            "Equipment Category",
                            "Action or Section",
                        }:
                            self.set_field(key, value, row)
                self.add_request(row, fields)
            elif self.event:
                for key, value in fields.items():
                    if key == "Equipment Category":
                        self.category = text(value)
                    elif key == "Action or Section":
                        self.section = text(value)
                    else:
                        self.set_field(key, value, row)
                # Ensure stray leading cells are never silently discarded.
                first = next(v for v in row.cells if text(v))
                if not table_row and not label(first) and not INLINE.match(text(first)):
                    self.issue(row, "Unparsed text", "Unlabelled text accompanies metadata.")
            else:
                self.issue(row, "Unattached metadata", "Metadata has no identifiable event block.")
            self.continuation = False
        elif (
            self.event
            and self.section
            and (
                split_request(row.text)[1] is not None
                or len(values) == 2
                and quantity(values[0]) is not None
            )
        ):
            self.raw.append(row.text)
            if len(values) == 2 and quantity(values[0]) is not None:
                self.add_request(row, {"Quantity": values[0], "Equipment Description": values[1]})
            else:
                self.add_request(row, {"Equipment Description": row.text})
        elif self.event and self.note_target:
            target = self.request if self.note_target == "request" else self.event
            assert target is not None
            self.append(
                target,
                "Request Notes" if self.note_target == "request" else "Event Notes",
                row.text,
            )
            self.raw.append(row.text)
        elif self.section:
            if self.event:
                self.raw.append(row.text)
            if len(values) == 2 and quantity(values[0]) is not None:
                self.add_request(row, {"Quantity": values[0], "Equipment Description": values[1]})
            else:
                self.add_request(row, {"Equipment Description": row.text})
        else:
            if self.event:
                self.raw.append(row.text)
            self.issue(row, "Unparsed row", "Row cannot be confidently classified.")

    def parse(self, rows: Iterable[SourceRow]) -> ParsedWorkbook:
        for row in rows:
            try:
                self.consume(row)
                for error in row.errors:
                    self.issue(row, "Source cell error", error)
                    if self.request and self.request["Source Row"] == row.number:
                        self.request["Data Quality Status"] = "Review required"
                        self.request["Quantity"] = None
            except (ValueError, TypeError, OverflowError) as exc:
                # Local conversion failures retain provenance and allow later records through.
                self.issue(
                    row, "Malformed record", f"Record conversion failed ({type(exc).__name__})."
                )
        self.finish()
        if not self.seen_content:
            raise ValueError("The workbook contains no event data.")
        groups: dict[tuple[str, str], list[Record]] = defaultdict(list)
        for event in self.result.events:
            for key in ("Parent Reservation ID", "Reservation ID"):
                if event.get(key):
                    groups[(key, text(event[key]))].append(event)
                    break
        for group_key, events in groups.items():
            if len(events) > 1:
                for event in events:
                    event["Recurrence ID"] = stable_id("REC", *group_key)
        return self.result
