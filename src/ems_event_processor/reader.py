"""Read Excel without ever saving or evaluating the source workbook."""

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import openpyxl
import xlrd
from xlrd.biffh import XLRDError

from .models import SourceRow, Value


class InputError(ValueError):
    """A source cannot be opened as a supported Excel workbook."""


def read_rows(path: Path) -> Iterator[SourceRow]:
    if path.suffix.lower() not in {".xls", ".xlsx"}:
        raise InputError("Choose a .xls or .xlsx Excel workbook.")
    if not path.is_file():
        raise InputError("The selected input file does not exist or is not a file.")
    try:
        if path.suffix.lower() == ".xlsx":
            yield from _xlsx(path)
        else:
            yield from _xls(path)
    except (OSError, ValueError, KeyError, EOFError, XLRDError) as exc:
        raise InputError(
            "Cannot read the Excel workbook. Check its format and access permissions."
        ) from exc
    except Exception as exc:
        # Corrupt ZIP/XML files surface several library-specific exception types.
        raise InputError("Cannot read the Excel workbook; it may be corrupt or encrypted.") from exc


def _xlsx(path: Path) -> Iterator[SourceRow]:
    book = openpyxl.load_workbook(path, data_only=False, read_only=False, keep_links=False)
    try:
        for sheet in book.worksheets:
            breaks = sorted(item.id for item in sheet.row_breaks.brk)
            page = 1 if breaks else None
            break_index = 0
            for number, cells in enumerate(sheet.iter_rows(), 1):
                while break_index < len(breaks) and number > breaks[break_index]:
                    page = (page or 1) + 1
                    break_index += 1
                errors = tuple(
                    "Formula or Excel error preserved; verify the source value."
                    for cell in cells
                    if cell.data_type in {"f", "e"}
                )
                values: tuple[Value, ...] = tuple(_value(cell.value) for cell in cells)
                yield SourceRow(path.name, sheet.title, number, page, values, errors)
    finally:
        book.close()


def _xls(path: Path) -> Iterator[SourceRow]:
    book = xlrd.open_workbook(str(path), formatting_info=True, on_demand=True)
    try:
        for sheet in book.sheets():
            breaks = sorted(item[0] for item in sheet.horizontal_page_breaks)
            page = 1 if breaks else None
            break_index = 0
            for index in range(sheet.nrows):
                while break_index < len(breaks) and index >= breaks[break_index]:
                    page = (page or 1) + 1
                    break_index += 1
                values: list[Value] = []
                errors: list[str] = []
                for cell in sheet.row(index):
                    value: Any = cell.value
                    if cell.ctype == xlrd.XL_CELL_DATE:
                        dt: datetime = xlrd.xldate_as_datetime(value, book.datemode)
                        value = dt.time() if 0 <= float(cell.value) < 1 else dt
                    elif cell.ctype == xlrd.XL_CELL_ERROR:
                        value = xlrd.error_text_from_code.get(value, f"Excel error {value}")
                        errors.append("Excel error preserved; verify the source value.")
                    elif cell.ctype in {xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK}:
                        value = None
                    elif isinstance(value, float) and value.is_integer():
                        value = int(value)
                    values.append(value)
                yield SourceRow(
                    path.name, sheet.name, index + 1, page, tuple(values), tuple(errors)
                )
    finally:
        book.release_resources()


def _value(value: Any) -> Value:
    if value is None or isinstance(value, (str, int, float, datetime)):
        return value
    from datetime import date, time

    if isinstance(value, (date, time)):
        return value
    return str(value)
