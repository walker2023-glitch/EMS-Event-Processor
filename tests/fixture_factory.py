"""Entirely invented examples matching the supplied worksheet's layout only."""

from pathlib import Path

import openpyxl
import xlwt
from openpyxl.worksheet.pagebreak import Break


def line(**columns):
    row = [None] * 23
    for column, value in columns.items():
        row[int(column[1:])] = value
    return row


def headers(day="Friday, November 6, 2026"):
    return [
        line(c11="Setup Worksheet"),
        line(c0="Brigham Young University - Idaho"),
        [],
        line(c22="Res ID     Book ID"),
        line(
            c1="Res Start",
            c2="Evt Start",
            c3="Evt End",
            c4="Res End",
            c6="Location / Event",
            c12="Setup / Event Type",
            c13="Group",
            c16="Status",
            c21="EC",
        ),
        line(c0=day),
    ]


def event(reservation, book, name, status="Confirmed", room="Example Hall"):
    return [
        line(
            c1="7:30 AM",
            c2="8:00 AM",
            c3="9:00 AM",
            c4="9:30 AM",
            c6=room,
            c12="Open Space",
            c13="Example Society",
            c16=status,
            c21="ZZ",
            c22=reservation,
        ),
        line(c22=book),
        line(c13="Example Contact 555-0100"),
        line(c6=name, c12="Meeting"),
        line(c13="Second Contact contact@example.invalid"),
    ]


def setup_rows():
    rows = headers()
    rows += event(1100, 91001, "Example Gathering", status="Confirmed - ")[:2]
    rows += [line(c15="Page 1 of 3"), line(c0="11/6/2026 10:02 AM TEST")]
    breaks = [len(rows)]
    rows += headers()
    rows += [line(c16="Calendar", c22=91001)]
    rows += event(1100, 91001, "Example Gathering")[2:]
    rows += [
        [],
        line(c6="A Student Event Coordinator"),
        line(c7=1, c9="Example Helper helper@example.invalid"),
        line(c9="Confirm the diagram with the source contact."),
        line(c6="An Event Timeline"),
        line(c9="8:00 AM - 9:00 AM EVENT"),
        line(c6="Facility Services Example"),
        line(c7=2, c9="Tables, 8' long  "),
        [],
        line(c7=12, c9="Chairs, folding"),
        line(c9="Place by the stage."),
    ]
    rows += event(2200, 92001, "Second Gathering")
    rows += [
        line(c22="*"),
        line(c6="Facility Services Example"),
        line(c7="a few", c9="Chairs, folding"),
        line(c7=3, c9="Tables, 8' long  "),
        line(c15="Page 2 of 3"),
        line(c0="11/6/2026 10:02 AM TEST"),
    ]
    breaks += [len(rows)]
    rows += headers("Saturday, November 7, 2026")
    rows += event(1100, 91002, "Example Gathering")
    rows += [
        line(c6="Facility Services Example", c7=4, c9="Chairs, folding"),
        line(c15="Page 3 of 3"),
    ]
    return rows, breaks


def write_rows(path: Path, rows, breaks=()):
    if path.suffix.lower() == ".xls":
        book = xlwt.Workbook()
        sheet = book.add_sheet("Setup")
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                if value is not None:
                    sheet.write(r, c, value)
        sheet.horz_page_breaks = [(r, 0, 22) for r in breaks]
        book.save(str(path))
    else:
        book = openpyxl.Workbook()
        sheet = book.active
        sheet.title = "Setup"
        for row in rows:
            sheet.append(row)
        for number in breaks:
            sheet.row_breaks.append(Break(id=number))
        book.save(path)
        book.close()
    return path


def generate(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    rows, breaks = setup_rows()
    for extension in (".xls", ".xlsx"):
        write_rows(directory / ("sanitized_setup" + extension), rows, breaks)


if __name__ == "__main__":
    generate(Path(__file__).parent / "fixtures")
