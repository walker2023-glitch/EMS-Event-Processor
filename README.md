# EMS Event Processor

A local, one-screen desktop app that turns an EMS Setup Worksheet `.xls` or
`.xlsx` report into organized Excel tables. Choose an input, click **Process
File**, choose where to save, and review the completion counts and any issues.
The original workbook is never saved or modified. Processing requires no account
or network access.

## Install and run

Use Python **3.11 or newer**, including Tkinter. On Windows, use the Python.org
installer with Tcl/Tk enabled. From this repository in PowerShell:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e .
.venv\Scripts\python -m ems_event_processor
```

On Linux/macOS, use `python3 -m venv .venv`, then `.venv/bin/python` for the
commands above. Linux needs its distribution's `python3-tk` package and a display.
The installed `ems-event-processor` command also opens the app.

## Output and review

- **Events**: one row per occurrence, with times, room, name, setup/type, group,
  contacts, source identifiers, notes, provenance and quality status.
- **Equipment Requests**: one row per equipment/service request, linked to its
  occurrence. Original request text and request notes remain available.
- **Equipment Summary**: totals by date, location, exact trimmed category and
  description. Only clearly parsed quantities with a description contribute.
- **`<output-stem>_issues.xlsx`**: created when any source information needs
  review. Includes original text, the problem, related IDs and source positions.

The output is always `.xlsx`. If replacing an existing output, its companion
issues file is replaced too; a stale issues file is removed on a clean rerun.
Files are staged together before publication, with rollback on ordinary save
failures. Close output files in Excel before processing them again.

See the [user guide](docs/user-guide.md), [column reference](docs/output-columns.md),
[developer notes](docs/development.md), and [verification record](docs/verification.md).

## Supported layout and limits

The parser supports the supplied 135-page Setup Worksheet's repeated headers,
merged report columns, wrapped metadata and requests continuing across pages.
It also supports explicit labeled blocks and event/equipment tables. Unknown
rows, malformed values and uninterpreted markers become issues. Coordinator
contacts and timeline notes are preserved separately from equipment totals.
Occurrences are never collapsed into a single recurring event.

Dates written as text use explicit US month/day/year, ISO dates, or month names;
ambiguous shorthand is preserved for review. Equipment descriptions are not fuzzy
matched, singularized, or merged across categories/locations/dates. Notes do not
create extra equipment or staffing requirements. `.xls` formula expressions are
not available through xlrd; its stored cell results are read. `.xlsx` formulas
are preserved as literal text and flagged; formulas are never evaluated.

A materially different report layout may require a parser change. The original
file remains the recovery source. EMS staff should review the first outputs
before operational use. Windows packaging is configured, but manual testing of
the executable on the intended employee Windows version remains a release gate.

This MVP does not create work orders, filter dates, upload files, or connect to a
website, SharePoint, Microsoft Graph or Power BI. It has no authentication,
cloud storage, mapping screens or AI interpretation.

## Tests and checks

```powershell
.venv\Scripts\python -m pip install -e '.[dev]'
.venv\Scripts\python -m pytest -q
.venv\Scripts\ruff check .
.venv\Scripts\ruff format --check .
.venv\Scripts\mypy
```

On Linux run `xvfb-run -a .venv/bin/python -m pytest -q` with Xvfb installed.
The UI tests use real Tk widgets and a real background processor, substituting
paths for native file-dialog selections. There are no private source workbooks
in the test suite. To rebuild invented fixtures: `python -m tests.fixture_factory`.

## Windows distribution

On Windows, run `powershell -File scripts/build-windows.ps1` after creating and
activating the virtual environment. Distribute the entire
`dist/EMS Event Processor/` directory, preferably zipped. Users launch
`EMS Event Processor.exe` without installing Python. GitHub Actions builds this
folder on Windows and publishes it as a workflow artifact. Follow the manual
release checklist in [developer notes](docs/development.md).
