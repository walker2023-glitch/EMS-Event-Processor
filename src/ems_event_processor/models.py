"""Internal data contracts; public workbook column names are deliberate."""

from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import TypeAlias

Value: TypeAlias = str | int | float | date | datetime | time | Decimal | None
Record: TypeAlias = dict[str, Value]

EVENT_COLUMNS = [
    "Event ID",
    "Parent Reservation ID",
    "Reservation ID",
    "Book ID",
    "Event Date",
    "Reservation Start",
    "Event Start",
    "Event End",
    "Reservation End",
    "Location",
    "Event Name",
    "Setup/Event Type",
    "Group",
    "Status",
    "Primary Contact",
    "Additional Contacts",
    "Event Notes",
    "Source File",
    "Source Page",
    "Source Row",
    "Data Quality Status",
    "Recurrence ID",
    "Source Sheet",
    "Original Source Text",
    "Event Type",
    "Event Coordinator",
    "Source Flags",
]
REQUEST_COLUMNS = [
    "Equipment Request ID",
    "Event ID",
    "Event Date",
    "Location",
    "Action or Section",
    "Equipment Category",
    "Equipment Description",
    "Quantity",
    "Original Request Text",
    "Request Notes",
    "Source File",
    "Source Page",
    "Source Row",
    "Data Quality Status",
    "Source Sheet",
]
SUMMARY_COLUMNS = [
    "Event Date",
    "Location",
    "Equipment Category",
    "Equipment Description",
    "Total Quantity",
    "Request Count",
]
ISSUE_COLUMNS = [
    "Issue ID",
    "Issue Type",
    "Severity",
    "Description",
    "Original Text",
    "Related Event ID",
    "Reservation ID",
    "Book ID",
    "Source File",
    "Source Page",
    "Source Row",
    "Suggested Review Action",
    "Source Sheet",
]


@dataclass(frozen=True)
class SourceRow:
    file: str
    sheet: str
    number: int
    page: int | None
    cells: tuple[Value, ...]
    errors: tuple[str, ...] = ()

    @property
    def text(self) -> str:
        cells = list(self.cells)
        while cells and cells[-1] in (None, ""):
            cells.pop()
        return " | ".join("" if v is None else str(v) for v in cells)

    def provenance(self) -> Record:
        return {
            "Source File": self.file,
            "Source Sheet": self.sheet,
            "Source Row": self.number,
            "Source Page": self.page,
        }


@dataclass
class ParsedWorkbook:
    events: list[Record] = field(default_factory=list)
    requests: list[Record] = field(default_factory=list)
    issues: list[Record] = field(default_factory=list)


@dataclass(frozen=True)
class ProcessingResult:
    output_path: Path | None = None
    issues_path: Path | None = None
    event_count: int = 0
    equipment_request_count: int = 0
    summary_row_count: int = 0
    issue_count: int = 0
    warnings: tuple[str, ...] = ()
    fatal_errors: tuple[str, ...] = ()

    @property
    def success(self) -> bool:
        return self.output_path is not None and not self.fatal_errors
