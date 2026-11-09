# Developer notes

## Structure

- `src/ems_event_processor/reader.py`: read-only access through openpyxl/xlrd;
  typed dates/times, physical sheet/row and available print-page provenance.
- `setup_worksheet.py`: supplied report adapter. The repeated `Res Start`,
  `Evt Start`, `Location / Event` header locates metadata columns. Detail quantity
  and description columns are the report's indents one and three columns after
  Location / Event. No fixed row numbers or page lengths are assumed.
- `parser.py`: event lifecycle, generic labels/tables, contacts/notes, issue
  creation and explicit recurrence links. `normalize.py` contains conversions.
- `models.py`: public result, internal records and exported column order.
- `summary.py`: Decimal accumulation with exact, trimmed description/category
  grouping; date and location stay in each grouping key.
- `exporter.py`: literal-only styled workbooks, text overflow, staged publication
  and ordinary-failure rollback. Readers never save the original workbook.
- `processor.py`: reusable local processing API and metadata-only logging.
- `ui.py`: one-screen Tk app; a worker performs processing and posts a queue.
  Only the main thread touches Tk. Closing during a run asks the user to wait.

## API

```python
from ems_event_processor import process_workbook

result = process_workbook("source.xls", "organized.xlsx", progress=print)
if result.success:
    print(
        result.output_path,
        result.issues_path,
        result.event_count,
        result.equipment_request_count,
        result.summary_row_count,
        result.issue_count,
    )
else:
    print(result.fatal_errors)
```

`warnings` and `fatal_errors` are tuples. Expected input/save failures return a
failed result with no published output path. Unexpected programmer errors propagate
to API callers; the UI catches them and displays a generic failure. A failed log
write produces a warning without invalidating successfully exported files.
`EMS_LOG_DIR` can redirect logs for automated tests or managed deployments.

Event/request IDs are deterministic hashes of source filename, sheet and row
coordinates (requests also include the event ID). They repeat on unchanged input
and avoid collisions between files with different names. Renaming a source,
changing its sheet name or moving rows changes IDs. They are source-position
identifiers, not a persistent work-order database. Reservation and Book IDs remain
source values. Recurrence links use shared parent reservation IDs, falling back
to shared reservation IDs; names and times are not evidence of recurrence.

## Parsing decisions

The inspected source has 463 time-bearing event headers across 135 pages. The
next ID-only row is the Book ID; a repeated Book ID at the next page anchors a
wrapped location, group or status. Event-name rows carry the event type, while
the time-bearing row carries the setup type. Coordinator initials and source
flags are separate columns. Asterisks remain uninterpreted issues.

The first Group-column detail is the primary contact; subsequent such details
are additional contacts. `A Student Event Coordinator` resource lines are contacts
and their descriptive notes remain event notes. `An Event Timeline` and explicit
setup/teardown note sections remain event notes. Service section labels are
preserved as both action/section and category. Numeric detail lines become
requests, including catering/services. Description-only continuation lines in a
service section attach to the preceding request; when no request precedes them,
they become an ambiguous request for review. Unknown rows always create issues.

Missing date, name or location triggers a review issue. Missing all source IDs
also triggers an issue. Other optional fields remain blank rather than invented.
An invalid source date/time remains its original string. Text dates use four-digit
years with US numeric ordering or ISO/month names. No timezone conversion occurs.
Blank rows do not terminate an occurrence. New time-bearing headers, explicit
new event blocks, event table records and changed date contexts do.

Quantity conversion accepts nonnegative explicit numbers, including decimals and
proper comma grouping. Inline requests need a clear quantity prefix/suffix;
measurement prefixes such as `6 ft Table` are ambiguous. Descriptions are only
trimmed; spelling, punctuation, case and internal whitespace remain significant.

## Verification and privacy

Install `.[dev]`, run pytest, ruff and mypy as in the README. UI tests require a
real or virtual display. Invented `.xls`/`.xlsx` fixtures and their generator are
under `tests/`; no provided workbook, source contacts, notes or generated real-data
outputs should be committed. Use ignored `work/` for private validation outputs.
The original sample is an external validation input, not a regression fixture.

See `verification.md` for measured results, AC review and unresolved release
checks. Before changing layout rules, add a sanitized regression, run both file
formats and inspect generated sheets. Source values that look like formulas are
written as literal strings. Excel-invalid control characters become visible
`\uXXXX` escapes; text above the cell length limit is preserved in an optional
`Text Continuations` sheet with sheet, row, column and ordered part references.

## Packaging and release gate

Use Python 3.12 on Windows and `scripts/build-windows.ps1` (from an activated
virtual environment). The spec builds an onedir, windowed PyInstaller application
including Tk, xlrd and openpyxl. PyInstaller does not cross-compile Windows apps
from Linux. CI tests Python 3.11/3.12 on Linux/Windows and builds one Windows artifact.
To use CI's artifact, download the full folder and launch the executable.

Before employee distribution:

- Confirm the supported Windows version with EMS; Windows 10/11 is the initial
  build target, subject to testing on the actual managed employee device.
- Run the Windows CI job and inspect its artifact, then launch the EXE on the
  intended Windows device with no Python installed.
- Use keyboard navigation and native dialogs to process both sanitized formats.
- Inspect all three organized sheets and the companion issues sheet; test a
  locked output file, canceling dialogs and a non-writable folder.
- Review source grouping, notes, contacts and quantities with EMS staff using an
  approved real file. Retain the original file and previous app build for rollback.
- Zip/distribute the full onedir folder; code signing and an installer are later
  distribution decisions, not implemented MVP features.

The exact employee OS and staff approval are unresolved plan questions. Future
website work must first investigate its actual API, authentication, field and
upload requirements. No endpoint or operational mapping is assumed here.
