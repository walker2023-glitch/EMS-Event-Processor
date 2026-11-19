# Backend verification record

The baseline was main commit `8e5b7d6`. Before implementation, all 106 desktop and
processor tests passed with a real Tk display. No file under
`src/ems_event_processor` was changed. The original parser, Excel resource totals,
issues workbook, source protection, desktop UI/themes/scaling and Windows
PyInstaller specification remain intact.

## Local results

Run with Python 3.12 and PostgreSQL 17 in a disposable container:

- `DISPLAY=:101 EMS_TEST_DATABASE_URL=<local-test-url> .venv/bin/pytest -q`:
  **147 passed** (106 original tests plus 41 backend cases).
- `.venv/bin/ruff check .`: passed.
- `.venv/bin/ruff format --check .`: passed.
- `.venv/bin/mypy`: passed with strict settings across both source packages.
- `EMS_TEST_DATABASE_URL=<local-test-url> .venv/bin/python -m scripts.smoke_backend_local`:
  passed over a real localhost HTTP server. Fictional invited admin accepted,
  both `.xls` and `.xlsx` uploaded, previews reviewed, imports approved, records
  and calendar created, planning updated, and four XLSX files downloaded. Final
  counts after the two imports: 3 events, 5 current resource requests, 3 calendar
  items. Source hashes and modification times remained unchanged.
- The optional fictional seed was tested with its guard both disabled and enabled.

A dependency emits a Starlette TestClient deprecation warning about httpx; the
real HTTP smoke test also passes and does not use TestClient. No test is changed
to suppress a failure or require a production credential.

## What the tests exercise

The integration tests apply the actual migration to fresh PostgreSQL databases.
Requests execute RPCs as an authenticated database role with a fictional user ID.
They verify API permissions and direct-DB privilege denials, inactive accounts,
revoked/expired invitations, last-admin protection, private Storage policies,
source immutability, malformed/oversized/expanded uploads, every workbook sheet,
resource totals, source-ID and normalized matching, explicit duplicate decisions,
stale previews, concurrent idempotent approval, rollback after a later candidate
fails, planning-note/manual-calendar preservation, generated calendar updates,
manual calendar types, filters, pagination, downloads, expiry and safe errors.

This is a documented **local Supabase substitute**, not a claim that hosted
Supabase was tested. Auth email confirmation and Storage bytes are simulated;
PostgreSQL, RLS, import transactions, parsing and XLSX generation are real.
HTTP transport contract tests separately verify user JWT headers, the invitation
service key boundary, REST/storage paths and safe provider error translation.

## CI and external checks

The existing Windows/Ubuntu and Python 3.11/3.12 matrix installs the optional backend
extras and runs tests, lint, formatting and mypy. Its Windows 3.12 job builds the
original executable and drives its native dialogs. A dedicated PostgreSQL service
job runs all backend cases and the real HTTP smoke test. The draft PR records the
actual run results; a configured workflow alone is not passing evidence.

No hosted Supabase URL, Auth admin key, frontend origin/callback, SMTP provider or
Vercel deployment credentials were configured for this task. Hosted invitation
emails, actual hosted object storage, Vercel execution and backup/restore remain
external acceptance checks. Employee-device Windows visual/DPI and EMS-staff
sample review remain the existing rollout gates. No branch merge is authorized
by this backend task; the work stays on a separate draft branch/PR.
