"""Readable literal-only Excel output and transactional workbook publication."""

import os
import re
import shutil
from datetime import date, datetime, time
from pathlib import Path
from tempfile import TemporaryDirectory

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo
from openpyxl.worksheet.worksheet import Worksheet

from .models import (
    EVENT_COLUMNS,
    ISSUE_COLUMNS,
    REQUEST_COLUMNS,
    SUMMARY_COLUMNS,
    ParsedWorkbook,
    Record,
)

ILLEGAL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def write_book(path: Path, sheets: list[tuple[str, list[str], list[Record]]]) -> None:
    book = Workbook()
    book.remove(book.worksheets[0])
    overflow: list[Record] = []
    try:
        for index, (title, columns, records) in enumerate(sheets, 1):
            sheet = book.create_sheet(title)
            sheet.append(columns)
            for row_number, record in enumerate(records, 2):
                for column_number, name in enumerate(columns, 1):
                    value = record.get(name)
                    if isinstance(value, str):
                        value = ILLEGAL.sub(lambda m: f"\\u{ord(m[0]):04x}", value)
                        if len(value) > 32000:
                            for offset in range(0, len(value), 30000):
                                overflow.append(
                                    {
                                        "Sheet": title,
                                        "Row": row_number,
                                        "Column": name,
                                        "Part": offset // 30000 + 1,
                                        "Original Text": value[offset : offset + 30000],
                                    }
                                )
                            value = value[:31000] + "\n[Full text in Text Continuations sheet]"
                    cell = sheet.cell(row_number, column_number, value)
                    if isinstance(value, str):
                        cell.data_type = "s"
                    if isinstance(value, (datetime, date)):
                        cell.number_format = "yyyy-mm-dd"
                    elif isinstance(value, time):
                        cell.number_format = "h:mm AM/PM"
                    elif name in {"Quantity", "Total Quantity"}:
                        cell.number_format = "#,##0.###"
                    cell.alignment = Alignment(vertical="top", wrap_text=True)
            _format(sheet, columns, index)
        if overflow:
            sheet = book.create_sheet("Text Continuations")
            columns = ["Sheet", "Row", "Column", "Part", "Original Text"]
            sheet.append(columns)
            for record in overflow:
                sheet.append([record[c] for c in columns])
                sheet.cell(sheet.max_row, 5).data_type = "s"
            _format(sheet, columns, len(sheets) + 1)
        book.save(path)
    finally:
        book.close()


def _format(sheet: Worksheet, columns: list[str], index: int) -> None:
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    sheet.sheet_view.zoomScale = 85
    sheet.row_dimensions[1].height = 32
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="234B66")
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    for i, name in enumerate(columns, 1):
        letter = get_column_letter(i)
        width = 48 if any(word in name for word in ("Text", "Notes", "Description")) else 23
        sheet.column_dimensions[letter].width = max(len(name) + 2, width)
    if sheet.max_row > 1:
        table = Table(displayName=f"EMSData{index}", ref=sheet.dimensions)
        table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
        sheet.add_table(table)


def export_workbooks(
    output: Path, issues: Path, parsed: ParsedWorkbook, summary: list[Record]
) -> None:
    """Stage all files before replacement; restore previous files on publication failure."""
    with TemporaryDirectory(prefix=".ems-", dir=output.parent) as temporary:
        staging = Path(temporary)
        main = staging / "output.xlsx"
        write_book(
            main,
            [
                ("Events", EVENT_COLUMNS, parsed.events),
                ("Equipment Requests", REQUEST_COLUMNS, parsed.requests),
                ("Equipment Summary", SUMMARY_COLUMNS, summary),
            ],
        )
        targets: list[tuple[Path | None, Path]] = [(main, output)]
        if parsed.issues:
            issue_file = staging / "issues.xlsx"
            write_book(issue_file, [("Issues", ISSUE_COLUMNS, parsed.issues)])
            targets.append((issue_file, issues))
        elif issues.exists():
            targets.append((None, issues))
        backups: dict[Path, Path] = {}
        for i, (_, target) in enumerate(targets):
            if target.exists():
                backup = staging / f"backup-{i}.xlsx"
                shutil.copy2(target, backup)
                backups[target] = backup
        published: list[Path] = []
        try:
            for staged, target in targets:
                if staged is None:
                    target.unlink()
                else:
                    os.replace(staged, target)
                published.append(target)
        except OSError:
            for target in reversed(published):
                if target in backups:
                    os.replace(backups[target], target)
                else:
                    target.unlink(missing_ok=True)
            raise
