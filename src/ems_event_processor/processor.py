"""Public processing API; fatal errors are returned, never reported as success."""

import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from .exporter import export_workbooks
from .models import ProcessingResult
from .parser import ReportParser
from .reader import InputError, read_rows
from .summary import summarize

Progress = Callable[[str], None]


def _same_file(left: Path, right: Path) -> bool:
    return left.resolve() == right.resolve() or (
        left.exists() and right.exists() and left.samefile(right)
    )


def _validate_paths(source: Path, output: Path, issues: Path) -> None:
    if source.suffix.lower() not in {".xls", ".xlsx"}:
        raise InputError("Choose a .xls or .xlsx Excel workbook.")
    if not source.is_file():
        raise InputError("The selected input file does not exist or is not a file.")
    if output.suffix.lower() != ".xlsx":
        raise ValueError("Save the output with an .xlsx extension.")
    for target in (output, issues):
        if _same_file(source, target):
            raise ValueError("The output or issues path would overwrite the original input.")
        if not target.parent.is_dir():
            raise ValueError("The output folder does not exist.")
        if target.exists() and not target.is_file():
            raise ValueError("The output path must be a file, not a folder.")
        if not os.access(target.parent, os.W_OK):
            raise ValueError("The output folder is not writable.")
    if _same_file(output, issues):
        raise ValueError("Output and issues paths must be different files.")


def process_workbook(
    input_path: str | Path, output_path: str | Path, progress: Progress | None = None
) -> ProcessingResult:
    """Process local files. Expected input/save failures are returned in fatal_errors.

    IDs are stable for unchanged sheet/row coordinates. Progress callbacks run on
    the caller's thread. Source values and contact details never enter the log.
    """
    source, output = Path(input_path).absolute(), Path(output_path).absolute()
    issues = output.with_name(output.stem + "_issues.xlsx")
    warnings: list[str] = []

    def notify(message: str) -> None:
        if progress:
            progress(message)

    try:
        _validate_paths(source, output, issues)
        notify("Reading the source workbook…")
        rows = list(read_rows(source))
        notify(f"Parsing {len(rows):,} source rows…")
        parsed = ReportParser().parse(rows)
        notify("Calculating equipment totals…")
        summary = summarize(parsed.requests)
        if not parsed.events:
            warnings.append(
                "No events recognized. Review the issues workbook before using the output."
            )
        if parsed.issues:
            warnings.append("Review the separate issues workbook before using these records.")
        notify("Saving organized workbooks…")
        export_workbooks(output, issues, parsed, summary)
        result = ProcessingResult(
            output,
            issues if parsed.issues else None,
            len(parsed.events),
            len(parsed.requests),
            len(summary),
            len(parsed.issues),
            tuple(warnings),
        )
    except (InputError, ValueError) as exc:
        result = ProcessingResult(fatal_errors=(str(exc),))
    except OSError:
        result = ProcessingResult(
            fatal_errors=(
                "Cannot save the output. Check folder permissions and close existing output files "
                "in Excel, then try again.",
            )
        )
    if not _log(source, output, result):
        from dataclasses import replace

        result = replace(
            result, warnings=(*result.warnings, "The local processing log could not be written.")
        )
    if result.success:
        notify("Processing complete.")
    return result


def _log(source: Path, output: Path, result: ProcessingResult) -> bool:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "state"))
    folder = Path(os.environ.get("EMS_LOG_DIR", base / "EMS Event Processor"))
    try:
        folder.mkdir(parents=True, exist_ok=True)
        log = folder / "processing.log"
        if log.exists() and log.stat().st_size > 1_000_000:
            log.replace(folder / "processing.previous.log")
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "input": source.name,
            "output": output.name,
            "events": result.event_count,
            "requests": result.equipment_request_count,
            "issues": result.issue_count,
            "status": "completed" if result.success else "input_or_save_error",
        }
        with log.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record) + "\n")
        return True
    except OSError:
        return False
