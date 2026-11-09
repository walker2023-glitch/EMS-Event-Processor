import hashlib
import os
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest

from ems_event_processor import process_workbook
from ems_event_processor.exporter import write_book
from ems_event_processor.models import SourceRow
from ems_event_processor.parser import ReportParser
from tests.fixture_factory import write_rows

FIXTURE = Path(__file__).parent / "fixtures" / "sanitized_setup.xlsx"


@pytest.mark.parametrize(
    "case",
    [
        "missing",
        "unsupported",
        "corrupt_xlsx",
        "corrupt_xls",
        "empty",
        "directory",
        "bad_suffix",
        "missing_folder",
        "same_source",
        "issues_is_source",
        "output_directory",
        "issues_directory",
    ],
)
def test_invalid_files_and_paths(case, tmp_path):
    source = tmp_path / "input.xlsx"
    source.write_bytes(FIXTURE.read_bytes())
    output = tmp_path / "out.xlsx"
    if case == "missing":
        source = tmp_path / "missing.xlsx"
    elif case == "unsupported":
        source = tmp_path / "input.csv"
        source.write_text("a,b")
    elif case.startswith("corrupt"):
        source = source.with_suffix(".xls" if case.endswith("xls") else ".xlsx")
        source.write_bytes(b"not an Excel file")
    elif case == "empty":
        write_rows(source, [])
    elif case == "directory":
        source.unlink()
        source.mkdir()
    elif case == "bad_suffix":
        output = tmp_path / "output.csv"
    elif case == "missing_folder":
        output = tmp_path / "missing" / "out.xlsx"
    elif case == "same_source":
        output = source
    elif case == "issues_is_source":
        source = tmp_path / "out_issues.xlsx"
        source.write_bytes(FIXTURE.read_bytes())
    elif case == "output_directory":
        output.mkdir()
    elif case == "issues_directory":
        (tmp_path / "out_issues.xlsx").mkdir()
    before = source.read_bytes() if source.is_file() else None
    result = process_workbook(source, output)
    assert not result.success and result.fatal_errors
    assert result.output_path is None
    if before is not None:
        assert source.read_bytes() == before


@pytest.mark.parametrize("kind", ["symlink", "hardlink"])
def test_link_cannot_overwrite_input(kind, tmp_path):
    source = tmp_path / "input.xlsx"
    source.write_bytes(FIXTURE.read_bytes())
    output = tmp_path / "out.xlsx"
    try:
        if kind == "symlink":
            output.symlink_to(source)
        else:
            os.link(source, output)
    except OSError:
        pytest.skip("OS does not permit file links for this user")
    assert not process_workbook(source, output).success
    assert source.read_bytes() == FIXTURE.read_bytes()


def test_unreadable_input(tmp_path, monkeypatch):
    def denied(*args, **kwargs):
        raise PermissionError("private source text must not enter logs")

    monkeypatch.setattr("ems_event_processor.reader.openpyxl.load_workbook", denied)
    result = process_workbook(FIXTURE, tmp_path / "out.xlsx")
    assert not result.success and "read" in result.fatal_errors[0]
    assert "private source text" not in (tmp_path / "logs" / "processing.log").read_text()


def test_unwritable_output(tmp_path, monkeypatch):
    monkeypatch.setattr("ems_event_processor.processor.os.access", lambda *args: False)
    result = process_workbook(FIXTURE, tmp_path / "out.xlsx")
    assert not result.success and "writable" in result.fatal_errors[0]


def test_failed_second_publication_restores_both_previous_outputs(tmp_path, monkeypatch):
    import ems_event_processor.exporter as exporter

    output = tmp_path / "out.xlsx"
    issues = tmp_path / "out_issues.xlsx"
    output.write_bytes(b"previous organized workbook")
    issues.write_bytes(b"previous issues workbook")
    original = exporter.os.replace

    def denied(source, target):
        if Path(source).name == "issues.xlsx":
            raise PermissionError("locked issues workbook")
        return original(source, target)

    monkeypatch.setattr(exporter.os, "replace", denied)
    result = process_workbook(FIXTURE, output)
    assert not result.success
    assert output.read_bytes() == b"previous organized workbook"
    assert issues.read_bytes() == b"previous issues workbook"
    assert not list(tmp_path.glob(".ems-*"))


def test_staging_failure_does_not_publish_partial_workbooks(tmp_path, monkeypatch):
    import ems_event_processor.exporter as exporter

    original = exporter.write_book

    def fail(path, sheets):
        if path.name == "issues.xlsx":
            raise OSError("disk full")
        return original(path, sheets)

    monkeypatch.setattr(exporter, "write_book", fail)
    result = process_workbook(FIXTURE, tmp_path / "out.xlsx")
    assert not result.success
    assert not (tmp_path / "out.xlsx").exists()
    assert not (tmp_path / "out_issues.xlsx").exists()


def test_no_issues_does_not_leave_previous_issues_workbook(tmp_path):
    source = write_rows(
        tmp_path / "source.xlsx",
        [
            ["Event Name: Complete"],
            ["Date: 2026-11-06"],
            ["Location: Hall"],
            ["Reservation ID: 1"],
            ["Equipment"],
            ["4 Chairs"],
        ],
    )
    issues = tmp_path / "out_issues.xlsx"
    issues.write_bytes(b"stale previous output")
    result = process_workbook(source, tmp_path / "out.xlsx")
    assert result.success and result.issues_path is None
    assert not issues.exists()


def test_log_failure_is_warning_not_false_processing_failure(tmp_path, monkeypatch):
    path = tmp_path / "blocked_log"
    path.write_text("not a directory")
    monkeypatch.setenv("EMS_LOG_DIR", str(path))
    result = process_workbook(FIXTURE, tmp_path / "out.xlsx")
    assert result.success and any("log" in w for w in result.warnings)


def test_formula_like_text_stays_literal_and_errors_are_flagged(tmp_path):
    source = write_rows(
        tmp_path / "source.xlsx",
        [
            ["Event Name: Complete"],
            ["Date: 2026-11-06"],
            ["Location: Hall"],
            ["Reservation ID: 1"],
            ["Equipment"],
            ["Qty", "Description"],
            [2, '=HYPERLINK("https://example.invalid","do not run")'],
        ],
    )
    before = hashlib.sha256(source.read_bytes()).digest()
    result = process_workbook(source, tmp_path / "out.xlsx")
    assert result.success and result.issue_count >= 1
    book = openpyxl.load_workbook(result.output_path)
    assert book["Equipment Requests"]["G2"].data_type == "s"
    assert book["Equipment Requests"]["G2"].value.startswith("=HYPERLINK")
    assert book["Equipment Requests"]["H2"].value is None
    book.close()
    assert hashlib.sha256(source.read_bytes()).digest() == before


def test_excel_cell_overflow_is_preserved_in_continuations(tmp_path):
    original = "=literal " + "long text " * 7000
    path = tmp_path / "long.xlsx"
    write_book(path, [("Events", ["Event Notes"], [{"Event Notes": original}])])
    book = openpyxl.load_workbook(path)
    chunks = [r[4] for r in list(book["Text Continuations"].values)[1:]]
    assert "".join(chunks) == original
    assert book["Text Continuations"]["E2"].data_type == "s"
    book.close()


def test_illegal_xml_characters_preserved_as_visible_escapes(tmp_path):
    path = tmp_path / "text.xlsx"
    write_book(path, [("Events", ["Text"], [{"Text": "before\x00after"}])])
    book = openpyxl.load_workbook(path)
    assert book["Events"]["A2"].value == "before\\u0000after"
    book.close()


def test_unknown_workbook_produces_review_output_with_zero_events(tmp_path):
    source = write_rows(tmp_path / "unknown.xlsx", [["unrecognized content"]])
    result = process_workbook(source, tmp_path / "out.xlsx")
    assert result.success and result.event_count == 0 and result.issues_path
    assert any("No events" in warning for warning in result.warnings)


def test_summary_excludes_missing_descriptions_and_ambiguous_quantities():
    from ems_event_processor.summary import summarize

    rows = [
        {"Quantity": None, "Equipment Description": "Tables"},
        {"Quantity": Decimal(3), "Equipment Description": ""},
        {"Quantity": Decimal(2), "Equipment Description": "Chairs"},
    ]
    assert summarize(rows)[0]["Total Quantity"] == 2
    assert len(summarize(rows)) == 1


def test_source_error_on_metadata_record_is_an_issue():
    row = SourceRow("test.xlsx", "Sheet1", 1, 1, ("Event Name: =formula",), ("Formula preserved",))
    result = ReportParser().parse([row])
    assert any(i["Issue Type"] == "Source cell error" for i in result.issues)


def test_distinct_identical_occurrences_are_not_deduplicated(tmp_path):
    source = write_rows(
        tmp_path / "source.xlsx",
        [
            ["Event Name", "Event Date", "Location", "Reservation ID"],
            ["Example", "2026-11-06", "Hall", "1"],
            ["Example", "2026-11-06", "Hall", "1"],
        ],
    )
    result = ReportParser().parse(read_rows_for_test(source))
    assert len(result.events) == 2
    assert len({e["Event ID"] for e in result.events}) == 2


def read_rows_for_test(source):
    from ems_event_processor.reader import read_rows

    return read_rows(source)
