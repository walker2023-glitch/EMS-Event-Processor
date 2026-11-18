import hashlib
import json
from collections import Counter
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest

from ems_event_processor import process_workbook
from ems_event_processor.models import (
    EVENT_COLUMNS,
    ISSUE_COLUMNS,
    REQUEST_COLUMNS,
    SUMMARY_COLUMNS,
)
from ems_event_processor.parser import ReportParser
from ems_event_processor.reader import read_rows
from tests.fixture_factory import event, headers, line, write_rows

FIXTURES = Path(__file__).parent / "fixtures"


def records(sheet):
    data = list(sheet.values)
    return [dict(zip(data[0], row, strict=True)) for row in data[1:]]


@pytest.mark.parametrize("extension", [".xls", ".xlsx"])
def test_setup_end_to_end(extension, tmp_path):
    source = FIXTURES / ("sanitized_setup" + extension)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    progress = []
    result = process_workbook(source, tmp_path / "organized.xlsx", progress.append)
    assert result.success, result.fatal_errors
    assert (result.event_count, result.equipment_request_count, result.issue_count) == (3, 5, 2)
    assert result.issues_path.is_file()
    assert progress[-1] == "Processing complete."
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    book = openpyxl.load_workbook(result.output_path)
    assert book.sheetnames == ["Events", "Equipment Requests", "Equipment Summary"]
    for name, columns in [
        ("Events", EVENT_COLUMNS),
        ("Equipment Requests", REQUEST_COLUMNS),
        ("Equipment Summary", SUMMARY_COLUMNS),
    ]:
        sheet = book[name]
        assert list(next(sheet.values)) == columns
        assert sheet.freeze_panes == "A2"
        assert sheet.auto_filter.ref == sheet.dimensions
        assert sheet.tables
        assert all(d.width >= 20 for d in sheet.column_dimensions.values())
    events = records(book["Events"])
    requests = records(book["Equipment Requests"])
    summary = records(book["Equipment Summary"])
    assert len({e["Event ID"] for e in events}) == 3
    assert events[0]["Recurrence ID"] == events[2]["Recurrence ID"]
    assert events[1]["Recurrence ID"] is None
    assert events[0]["Status"] == "Confirmed - Calendar"
    assert events[0]["Primary Contact"] == "Example Contact 555-0100"
    assert "helper@example.invalid" in events[0]["Additional Contacts"]
    assert events[0]["Setup/Event Type"] == "Open Space"
    assert events[0]["Event Type"] == "Meeting"
    assert events[0]["Event Date"] == datetime(2026, 11, 6)
    assert events[2]["Event Date"] == datetime(2026, 11, 7)
    assert events[0]["Event Start"] == time(8)
    assert events[0]["Source Row"] == 7
    assert events[0]["Source Page"] == 1
    assert events[2]["Source Page"] == 3
    assert "8:00 AM - 9:00 AM EVENT" in events[0]["Event Notes"]
    assert requests[1]["Request Notes"] == "Place by the stage."
    assert requests[2]["Quantity"] is None
    assert "a few" in requests[2]["Original Request Text"]
    assert all(r["Event ID"] in {e["Event ID"] for e in events} for r in requests)
    tables = [r for r in summary if r["Equipment Description"].startswith("Tables")]
    assert len(tables) == 1 and tables[0]["Total Quantity"] == 5
    assert tables[0]["Request Count"] == 2
    assert sorted(r["Total Quantity"] for r in summary) == [4, 5, 12]
    assert book["Events"]["E2"].number_format == "yyyy-mm-dd"
    assert book["Equipment Requests"]["H2"].number_format == "#,##0.###"
    book.close()
    issues = openpyxl.load_workbook(result.issues_path)
    assert list(next(issues["Issues"].values)) == ISSUE_COLUMNS
    problems = records(issues["Issues"])
    assert {p["Issue Type"] for p in problems} == {"Uninterpreted marker", "Ambiguous equipment"}
    assert all(p["Source Row"] and p["Source Sheet"] for p in problems)
    issues.close()
    again = process_workbook(source, tmp_path / "again.xlsx")
    book = openpyxl.load_workbook(again.output_path)
    assert [e["Event ID"] for e in records(book["Events"])] == [e["Event ID"] for e in events]
    book.close()


def parse(rows, tmp_path, extension=".xlsx"):
    path = write_rows(tmp_path / ("source" + extension), rows)
    return ReportParser().parse(read_rows(path))


def test_generic_labels_multiple_occurrences_and_notes(tmp_path):
    result = parse(
        [
            ["Setup Worksheet"],
            ["Date:", "11/06/2026"],
            ["Reservation ID:", "00110"],
            ["Event Name: Example", "Location: Hall", "Event Time: 8:00 AM - 9:00 AM"],
            ["Contact:", "First Contact"],
            ["Contact:", "Second Contact"],
            ["Equipment"],
            ["4 Chairs"],
            [],
            ["Notes: Near stage"],
            ["and along wall"],
            ["2 x Tables"],
            ["Date:", "11/07/2026"],
            ["Reservation ID: 00110"],
            ["Event Name: Example"],
            ["Location: Hall"],
            ["Equipment"],
            ["3 Chairs"],
        ],
        tmp_path,
    )
    assert len(result.events) == 2
    assert len(result.requests) == 3
    assert result.events[0]["Reservation ID"] == "00110"
    assert result.events[0]["Event Start"] == time(8)
    assert result.events[0]["Additional Contacts"] == "Second Contact"
    assert result.requests[0]["Request Notes"] == "Near stage\nand along wall"
    assert result.events[0]["Recurrence ID"] == result.events[1]["Recurrence ID"]
    assert result.requests[2]["Event Date"] == date(2026, 11, 7)


def test_event_and_equipment_tables(tmp_path):
    result = parse(
        [
            ["Event Date", "Event Name", "Location", "Reservation ID"],
            ["2026-11-06", "First", "Hall", "1"],
            ["Qty", "Description", "Request Notes"],
            [2, "Tables", "Near wall"],
            ["a few", "Chairs", "Verify"],
            ["Event Date", "Event Name", "Location", "Reservation ID"],
            ["2026-11-07", "Second", "Room", "2"],
            ["Qty", "Description"],
            [4, "Chairs"],
        ],
        tmp_path,
    )
    assert [e["Event Name"] for e in result.events] == ["First", "Second"]
    assert [r["Quantity"] for r in result.requests] == [Decimal(2), None, Decimal(4)]
    assert result.requests[0]["Request Notes"] == "Near wall"
    assert len(result.issues) == 1


def test_missing_invalid_and_unknown_values_do_not_drop_good_event(tmp_path):
    result = parse(
        [
            ["Event Name: Incomplete"],
            ["Event Date: next Friday"],
            ["Event Start: lunchtime"],
            ["Mystery source value"],
            ["Equipment"],
            ["Chairs as needed"],
            ["Event Name: Complete"],
            ["Date: 2026-11-07"],
            ["Location: Hall"],
            ["Reservation ID: 2"],
            ["Equipment"],
            ["2 Tables"],
        ],
        tmp_path,
    )
    assert len(result.events) == 2 and len(result.requests) == 2
    assert result.events[0]["Event Date"] == "next Friday"
    assert result.events[0]["Event Start"] == "lunchtime"
    assert result.events[0]["Data Quality Status"] == "Review required"
    assert result.events[1]["Data Quality Status"] == "OK"
    assert {i["Issue Type"] for i in result.issues} >= {
        "Invalid date",
        "Invalid time",
        "Missing event value",
        "Missing identifiers",
        "Unparsed row",
        "Ambiguous equipment",
    }


def test_orphan_data_is_preserved(tmp_path):
    result = parse([["Equipment"], ["4 Chairs"], ["Something unrecognized"]], tmp_path)
    assert not result.events
    assert any(i["Original Text"] == "4 Chairs" for i in result.issues)
    assert all(i["Source Row"] for i in result.issues)


def test_malformed_record_isolated(tmp_path, monkeypatch):
    original = ReportParser.set_field

    def broken(self, key, value, row):
        if value == "Malformed":
            raise ValueError("deliberately broken record")
        return original(self, key, value, row)

    monkeypatch.setattr(ReportParser, "set_field", broken)
    result = parse(
        [
            ["Event Name: Malformed"],
            ["Event Name: Good"],
            ["Location: Hall"],
            ["Date: 2026-11-07"],
            ["Reservation ID: 1"],
        ],
        tmp_path,
    )
    assert any(e.get("Event Name") == "Good" for e in result.events)
    assert any(i["Issue Type"] == "Malformed record" for i in result.issues)


@pytest.mark.parametrize("extension", [".xls", ".xlsx"])
def test_typed_dates_times(extension, tmp_path):
    if extension == ".xls":
        import xlwt

        path = tmp_path / "source.xls"
        book = xlwt.Workbook()
        sheet = book.add_sheet("Typed")
        rows = [
            ["Event Name", "Typed"],
            ["Date", datetime(2026, 11, 6)],
            ["Event Start", 0.5],
            ["Location", "Hall"],
            ["Reservation ID", 1],
        ]
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                style = (
                    xlwt.easyxf(num_format_str="yyyy-mm-dd")
                    if isinstance(value, datetime)
                    else xlwt.easyxf(num_format_str="h:mm")
                    if r == 2 and c == 1
                    else xlwt.Style.default_style
                )
                sheet.write(r, c, value, style)
        book.save(str(path))
        parsed = ReportParser().parse(read_rows(path))
    else:
        parsed = parse(
            [
                ["Event Name", "Typed"],
                ["Date", datetime(2026, 11, 6)],
                ["Event Start", time(12)],
                ["Location", "Hall"],
                ["Reservation ID", 1],
            ],
            tmp_path,
        )
    assert parsed.events[0]["Event Date"] == date(2026, 11, 6)
    assert parsed.events[0]["Event Start"] == time(12)


def test_log_does_not_contain_source_contacts_or_notes(tmp_path):
    result = process_workbook(FIXTURES / "sanitized_setup.xlsx", tmp_path / "output.xlsx")
    assert result.success
    log = (tmp_path / "logs" / "processing.log").read_text()
    assert "Contact" not in log and "example.invalid" not in log and "diagram" not in log
    assert json.loads(log)["events"] == 3


def test_repeated_header_and_blank_rows_keep_request_link(tmp_path):
    rows = (
        headers()
        + event(1, 2, "Test")
        + [line(c6="Facility Services Example"), line(c7=2, c9="Tables"), []]
    )
    rows += headers() + [line(c7=4, c9="Chairs")]
    parsed = parse(rows, tmp_path)
    assert len(parsed.events) == 1 and len(parsed.requests) == 2
    assert len({r["Event ID"] for r in parsed.requests}) == 1
    assert not parsed.issues


def test_no_fuzzy_equipment_merging(tmp_path):
    rows = (
        headers()
        + event(1, 2, "Test")
        + [
            line(c6="Facility Services Example"),
            line(c7=2, c9="Chair"),
            line(c7=3, c9="Chairs"),
            line(c7=4, c9="Chair, grey"),
        ]
    )
    source = write_rows(tmp_path / "source.xlsx", rows)
    result = process_workbook(source, tmp_path / "out.xlsx")
    assert result.summary_row_count == 3


def test_source_sheet_boundaries_reset_date_context(tmp_path):
    path = write_rows(tmp_path / "source.xlsx", [["Date: 2026-11-06"], ["Event Name: First"]])
    book = openpyxl.load_workbook(path)
    sheet = book.create_sheet("Other")
    sheet.append(["Event Name: Second"])
    book.save(path)
    book.close()
    parsed = ReportParser().parse(read_rows(path))
    assert len(parsed.events) == 2
    assert parsed.events[1]["Event Date"] is None
    assert parsed.events[0]["Event ID"] != parsed.events[1]["Event ID"]


def test_every_source_service_count_is_accounted_for():
    parsed = ReportParser().parse(read_rows(FIXTURES / "sanitized_setup.xls"))
    assert Counter(r["Source Row"] for r in parsed.requests).most_common(1)[0][1] == 1


def test_wrapped_location_group_and_event_type(tmp_path):
    rows = headers() + event(1, 2, "Example", room="Long Room")[:2]
    rows += headers() + [line(c6="Extension", c13="Continuation", c16="Calendar", c22=2)]
    rows += event(1, 2, "Example")[2:4] + headers() + [line(c12="Continuation Type")]
    rows += [line(c6="Facility Services Example"), line(c7=3, c9="Tables")]
    parsed = parse(rows, tmp_path)
    assert len(parsed.events) == 1
    assert parsed.events[0]["Location"] == "Long Room Extension"
    assert parsed.events[0]["Group"] == "Example Society Continuation"
    assert parsed.events[0]["Event Type"] == "Meeting\nContinuation Type"
    assert parsed.requests[0]["Location"] == "Long Room Extension"


def test_missing_report_name_is_not_invented_from_service_heading(tmp_path):
    rows = headers() + event(1, 2, "Ignored")[:3]
    rows += [line(c6="Facility Services Example"), line(c7=2, c9="Tables")]
    parsed = parse(rows, tmp_path)
    assert not parsed.events[0].get("Event Name")
    assert len(parsed.requests) == 1
    assert any(i["Issue Type"] == "Missing event value" for i in parsed.issues)


def test_generic_mixed_table_keeps_event_fields_and_requests(tmp_path):
    parsed = parse(
        [
            ["Event Name", "Location", "Event Date", "Reservation ID", "Qty", "Description"],
            ["Example", "Hall", "2026-11-06", "1", 3, "Tables"],
        ],
        tmp_path,
    )
    assert parsed.events[0]["Event Name"] == "Example"
    assert parsed.events[0]["Location"] == "Hall"
    assert parsed.requests[0]["Quantity"] == 3


def test_unlabelled_metadata_cell_creates_review_issue(tmp_path):
    parsed = parse(
        [
            ["Event Name: Example", "unknown extra text"],
            ["Location: Hall"],
            ["Date: 2026-11-06"],
            ["Reservation ID: 1"],
        ],
        tmp_path,
    )
    assert any(
        i["Issue Type"] == "Unparsed text" and "unknown extra text" in i["Original Text"]
        for i in parsed.issues
    )


def test_raw_text_keeps_source_trailing_characters():
    from ems_event_processor.models import SourceRow

    row = SourceRow("source.xlsx", "Sheet", 1, None, (None, "uncertain |  ", None))
    assert row.text == " | uncertain |  "


def test_setup_formula_metadata_is_preserved_and_flagged(tmp_path):
    rows = headers() + event(1, 2, "Example")
    rows += [line(c6="Facility Services Example"), line(c7=2, c9="Tables")]
    # Formula occurs in the contact detail, exercising an adapter early return.
    rows[8] = line(c13='=CONCAT("Uncertain", " Contact")')
    parsed = parse(rows, tmp_path)
    assert any(i["Issue Type"] == "Source cell error" for i in parsed.issues)
    assert "=CONCAT" in parsed.events[0]["Original Source Text"]
