# EMS Planner backend setup

The optional FastAPI backend reuses the existing Excel reader, parser, resource
summary and workbook exporter. The desktop app keeps its original dependencies,
entry point, UI and Windows packaging. There are no frontend changes.

The implementation supports one shared workspace. Supabase supplies Auth,
PostgreSQL, private Storage and Row Level Security. Event approval runs as one
PostgreSQL transaction; browser visibility never substitutes for permission checks.

## Local API

Use Python 3.11 or 3.12, including Tk for the desktop regression suite:

```sh
python -m venv .venv
.venv/bin/python -m pip install -e '.[dev,backend,backend-test]'
```

On Windows use `.venv\Scripts\python` and the corresponding Scripts executables.
Set environment variables through your shell or host secret manager. The
[.env.example](../../.env.example) contains placeholders. No environment file is
read automatically. To use a local `.env`, install `python-dotenv` in the virtual
environment and pass `--env-file .env` to Uvicorn. `.env` files are ignored by Git.

```sh
.venv/bin/python -m uvicorn ems_backend.app:app --host 127.0.0.1 --port 8000
```

`GET /health` works without Supabase and reports `configured: false`. It is a
liveness/configuration check, not a database connection probe. Data requests
without configuration return 503. Interactive OpenAPI is at `/docs`, ReDoc at
`/redoc`, and the machine-readable contract is at `/openapi.json`.

## Supabase configuration

Create a development project before using real staff data. Use migrations via
Supabase CLI; do not manually create production tables. Link only the project you
intend to change, review the migration, and run `supabase db push` against that
explicitly selected development project. This work has not pushed any hosted
migration or configured a production project.

Required server settings:

| Variable | Value and purpose |
| --- | --- |
| `SUPABASE_URL` | Project HTTPS URL from Supabase project settings. |
| `SUPABASE_ANON_KEY` | Project anon JWT or publishable API key, used with each caller's access token. The frontend may also use this public key. |
| `SUPABASE_SERVICE_ROLE_KEY` | Server-only legacy `service_role` JWT, used only to call GoTrue's admin invitation endpoint. Never include it in frontend environment bundles. A new-format secret key is not tested as a replacement for this JWT. |
| `CORS_ORIGINS` | Comma-separated exact frontend origins, such as the actual development and deployed frontend URLs. No wildcard. |
| `INVITE_REDIRECT_URL` | Frontend invitation callback URL. Add it to Supabase Auth's allowed redirect URLs. |
| `CALENDAR_TIMEZONE` | IANA timezone for source workbook dates/times; defaults to `America/Denver`. |
| `MAX_UPLOAD_BYTES` | Default `3000000`; keep the small default for a Vercel trial. |

Configure Supabase Auth to **disable public sign-up**, require email confirmation,
and use an appropriate SMTP provider. Local CLI config also disables sign-up.
The database additionally rejects new Auth users without a pending, unexpired,
unrevoked invitation. Never bootstrap users from user-editable Auth metadata.

The migration creates the private `ems-private` bucket and its policies. Keep it
private. Originals are immutable insert-only objects; neither the API nor its
users have an overwrite/delete path. Export reads require an active account and
an approved import (admins can inspect preapproval exports). Data/Storage use the
user JWT; the service-role key is not used as a general data-access bypass.

### Bootstrap the first real administrator

A database/project owner must do this once; no public bootstrap HTTP route exists.
In the selected development project's SQL editor, create a pending invitation for
the intended administrator's email with `role='admin'` and `created_by=NULL`.
Then use Supabase Auth's admin invitation facility to send that email its invite.
The Auth trigger creates an inactive profile. The recipient follows the invite,
sets a password if desired, and calls `POST /auth/accept-invitation` after the
email is verified. Subsequent invitations go through the admin API.

Example SQL template; replace the placeholder privately in the SQL editor:

```sql
insert into public.invitations(email, role)
values ('YOUR_ADMIN_EMAIL', 'admin');
```

Do not activate a profile just because the browser requests an admin role.
Accepted accounts get the role stored in the invitation. Deactivation takes
effect on the next API/DB request even while an old access token remains unexpired.
The final active administrator cannot demote or deactivate themselves.

### Optional fictional seed

`supabase/seed.sql` is disabled by default. It contains fictional users, an event,
a resource and a calendar item. Seeded users have no usable login credentials.
Only run it in a disposable local project, deliberately setting the session flag
`ems.allow_fictional_seed=on`. Never run it in a shared or production database.
It is a one-time seed, not an idempotent reset of existing user data.

## Tests without a Supabase project

The regular backend unit tests use no live service. The integration suite and
HTTP smoke test use a disposable **local PostgreSQL 17** service. They create and
remove uniquely named databases; they do not modify an existing application DB.
Use a disposable PostgreSQL instance with a local database-owner test account.

```sh
# Set this to your disposable local instance, never production credentials.
export EMS_TEST_DATABASE_URL='postgresql://USER:PASSWORD@127.0.0.1:5432/postgres'
DISPLAY=:99 .venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/mypy
.venv/bin/python -m scripts.smoke_backend_local
```

Set `DISPLAY` to a running X display on Linux, or use `xvfb-run -a`; Windows tests
use their desktop display. Without `EMS_TEST_DATABASE_URL`, PostgreSQL cases are
explicitly skipped; this is not evidence that RLS passed. CI has a dedicated
PostgreSQL job that runs them and the real HTTP smoke test.

The local substitute uses the **shipped migration, actual PostgreSQL transactions,
actual authenticated database roles and RLS**, the real parser, and generated Excel
files. It simulates email confirmation and keeps Storage bytes in memory while
checking the real `storage.objects` RLS policies. Its fictional bearer tokens are
user UUIDs. This substitute exists only in development tests/scripts; the deployed
API validates bearer tokens with Supabase Auth's `/auth/v1/user` endpoint.
It does not establish SMTP delivery, GoTrue invite links, hosted Storage behavior,
or hosted Vercel behavior. Those need a configured development project.
