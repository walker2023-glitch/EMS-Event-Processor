# MVP verification record

Validated 2026-11-09 against `plan/1.1_ems_event_processor_mvp.md`. Every section,
functional requirement and all nine acceptance criteria were reviewed. Platform
release checks below remain explicit; passing local tests does not establish
manual Windows-device or EMS-staff acceptance.

## Evidence

- **83 tests pass** in each CI job on Windows and Ubuntu with Python 3.11 and
  3.12. The local Linux/Python 3.12.14 run also has **93% statement coverage**.
  Automated tests cover both `.xls` and `.xlsx`, real Tk
  widgets and worker processing, parsing, date/time/contact/quantity handling,
  event/equipment table export, recurrence, issue creation, invalid inputs/paths,
  source bytes, links to source, staging/rollback, text preservation and logging.
- `ruff check .`, `ruff format --check .` and strict `mypy` pass in all four
  CI jobs. Windows-platform mypy also passes locally.
- The Windows Python 3.12 CI job successfully builds the PyInstaller executable,
  launches its real Tk window and closes it through the normal window message.
  The full onedir distribution is published as a 13.2 MB ZIP artifact.
  [Passing CI run](https://github.com/walker2023-glitch/EMS-Event-Processor/actions/runs/42665123314) ·
  [Windows artifact](https://github.com/walker2023-glitch/EMS-Event-Processor/actions/runs/42665123314/artifacts/13696416074).
- The same spec also builds and opens a Linux executable. This environment's
  custom Tcl 9 runtime required its Python library directory on LD_LIBRARY_PATH
  during that Linux build. The Windows Python.org build needs no such adjustment.
- The user-supplied Setup Worksheet was inspected and processed as the primary
  layout example. It contains **135 printed pages and 6,373 physical rows**.
  Output: **463 occurrences, 1,621 requests, 1,089 summary rows, 86 issues**.
- An independent source-row audit accounted for every time-bearing event header
  and every non-coordinator numeric service row. Quantities, descriptions, event
  links, dates, locations, categories and every summary total/request count match.
  The independent sum of requested quantities is **27,401** (across diverse item
  types; this is an audit checksum, not an operational inventory figure).
- Full-sample processing took approximately **1.5 seconds** in this environment.
  The entire supplied workbook was also processed through real Tk widgets and
  the background worker with controlled native-dialog path returns; the event
  loop remained responsive and the completion screen was visually inspected.
  All resulting UI-run workbooks were reopened and checked as well.
- Both generated sample workbooks were reopened with openpyxl. All sheets,
  column orders, IDs/relationships, filters, frozen headers, tables, date/time/
  quantity formats and review records were inspected programmatically.
- All **86** sample issues are uninterpreted source asterisk markers. None is
  assigned an invented meaning. No sample event or request row was dropped.
- Input SHA-256 bytes and filesystem modification time remained unchanged.
- The supplied workbook, source names/contacts/notes, generated real-data files
  and audit scratch scripts stay outside version control. Fixtures are invented.

## Acceptance criteria

| Criterion | Result | Evidence |
| --- | --- | --- |
| AC-1: select/read both formats and save output | Pass | Parametrized integration tests plus Tk choose/process/save flow. |
| AC-2: organized Setup Worksheet records | Pass | Full sample source-row audit; repeated headers/footer timestamps excluded; wrapped fields and page continuations verified. |
| AC-3: one event, separate equipment rows | Pass | Invented multi-request fixture, preserved occurrence/request foreign keys, 463/1,621 sample counts. |
| AC-4: correct quantities/totals | Pass | Independent audit of all sample summary rows; ambiguous quantities excluded; exact-description grouping tests. |
| AC-5: ambiguity preserved and issues generated | Pass | Unknown quantities/rows, invalid dates/times, formulas and all 86 real source markers retain original text and provenance. |
| AC-6: recurring occurrences stay separate | Pass | Repeated source reservations retain separate IDs/rows and shared recurrence links; identical occurrences are not deduplicated. |
| AC-7: bad record does not block valid records | Pass | Mixed malformed/valid inputs and injected per-record conversion failure export valid records and review issues. |
| AC-8: clear errors, no false success | Pass | Real UI error tests for unreadable input/invalid save folder, plus engine locked-save/rollback/path tests. |
| AC-9: input unchanged | Pass | Source hashes, modification time, direct/derived-path collision and symlink/hardlink rejection. |

## Functional and non-functional review

FR-1–4: single Tk screen, input dialogs for both extensions, visible selected path,
output save dialog. FR-5–6: source never saved; blank rows, printed breaks and
repeated headers supported. FR-7–14: suggested tables/columns, separate linked
requests, exact quantity totals, raw text/provenance and explicit recurrence.
FR-15–16: separate issues workbook with all suggested review/provenance fields.
FR-17–19: queued progress, completion counts/paths and clear read/save errors.
FR-20: source values only, no invented operational data.

Performance was measured on the actual sample. The worker and Tk queue keep
processing off the UI thread. All runtime workbook processing is local with no
credentials/network libraries. Labels, focusable controls, readable status and
errors support keyboard use without relying on color. Logs contain metadata
only. Record-level errors are isolated. Parsing, normalization, totals, export
and UI are separate modules. Source preservation is covered throughout.

## Remaining release validation

- Manually test native dialogs and Excel file locking on the intended employee
  Windows device. Automated Windows tests and the packaged-window smoke check
  pass, but no employee device was available for manual distribution testing.
- Have EMS staff review real grouping, note placement, contacts, source flags and
  totals before final rollout/pilot. Staff approval and the meaning of asterisks
  were not supplied. The open questions in the plan remain future decisions.
- Native file dialog interaction is exercised with controlled path returns in
  automated Tk tests; interactive native dialog operation is a manual release check.

These are unverified release/rollout steps, not claims of completed manual tests.
No future website, work orders, authentication or other excluded integration was
added. Website requirements must be investigated when that service is available.
