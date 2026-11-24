# Neon migration preflight

Status: infrastructure declaration prepared; application migration and remote
service verification are not complete. No Neon project or branch has been linked,
no remote service has been provisioned, and no database data has been changed.
The existing Supabase backend remains operational on this preparatory branch.

The user-selected target is project `restless-grass-51807778`
(`ems-event-planner-dev`), branch `development`. The Cloud CLI has not yet received
a successful authentication callback, so that branch's remote ID, default/protected
flags and service capabilities have not been verified. Never fall back to the
production/default branch. A provisioning-only project-scoped NEON_API_KEY may
be supplied privately in an ignored local .env if browser login cannot finish;
never include that management key in frontend code or application responses.

## Repository inspection

- FastAPI: `src/ems_backend/app.py`, entered through `api/index.py` for Vercel.
- Supabase configuration and REST/Auth/Storage adapter:
  `src/ems_backend/config.py` and `src/ems_backend/gateway.py`.
- Database, row policies, invitation triggers and transactional RPCs:
  `supabase/migrations/202611190001_ems_backend.sql`. These depend on
  `auth.users`, `auth.uid()`, `storage.objects` and Supabase database roles.
- Frontend integration: bearer-authenticated HTTP endpoints, CORS environment
  configuration, `docs/backend/api-contract.md`, and `docs/backend/openapi.json`.
  There was no frontend package or frontend build script in this checkout.
- Parser, workbook processing/export and offline desktop UI:
  `src/ems_event_processor/`; these do not need a provider migration.
- Tests/build: `pytest -q`, `ruff check .`, `ruff format --check .`, `mypy`;
  PostgreSQL integration and real-HTTP smoke instructions are in
  `docs/backend/setup.md`. Windows packaging uses the existing PyInstaller spec
  and PowerShell script, with native UI smoke checks in CI.
- There was no `neon.ts`. The new root declaration is infrastructure only. Its
  small npm package does not introduce or replace a frontend; it has no build script.

## Replacement boundaries

1. Replace PostgREST HTTP queries and RPC transport with psycopg PostgreSQL calls,
   using DATABASE_URL for application work. Use DATABASE_URL_UNPOOLED for migrations.
   Keep the existing import approval transaction, matching, history and concurrency
   protection. Set verified user context transaction-locally with a restricted
   runtime role; do not run user requests with migration-owner privileges.
2. Replace Supabase Auth and auth.users triggers with Managed Better Auth identity
   verification and application-controlled invitations/profiles. Validate JWT
   signature, issuer, audience and expiration against the selected branch's JWKS.
   Do not equate a successful public Auth signup with employee membership.
3. Replace Supabase bucket policies and storage HTTP calls with private S3-compatible
   storage. Enforce permissions before every file operation, retain immutable source
   bytes, and expose authenticated API downloads rather than public URLs.
4. Replace Supabase RLS helper dependencies with explicit application identity and
   corresponding database policies/functions. Preserve roles and planning data.
5. Change event planning status values to Not reviewed, Needs discussion,
   Ready to plan and Confirmed. Do not silently equate legacy Complete with
   Confirmed. Preserve legacy values for review when migrating existing data;
   task/calendar status semantics must be reviewed separately from event planning.

## Infrastructure declaration and deployment gate

`neon.ts` declares managed Auth and exactly one private bucket named uploads.
It does not deploy the Python application or apply application migrations.
Before linking or deploying, obtain the user's exact project and development
branch names/IDs, authenticate, inspect that branch and confirm it is not the
production target. Do not run init/claim against an arbitrary new project.

Use the requested CLI (`npm i -g neon@latest`, with `npx neon@latest` as fallback).
In this environment the global install failed at its configured install prefix;
the npx CLI works. Store CLI credentials outside the repository. Browser login
must finish in the same Cloud computer because its callback uses localhost.
Never paste credentials into chat or print connection strings.

Once the target is verified, link that development branch, review the config
plan, then deploy the declared services. Provisioning or migrations must wait
until the user has identified the intended development branch.

Expected server variables, without values:

- DATABASE_URL and DATABASE_URL_UNPOOLED
- NEON_AUTH_BASE_URL and NEON_AUTH_JWKS_URL
- AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_ENDPOINT_URL_S3, AWS_REGION
- CORS_ORIGINS, INVITE_REDIRECT_URL, CALENDAR_TIMEZONE and MAX_UPLOAD_BYTES

Neon env output belongs in ignored local .env/.env.local files and deployment
secrets, never Git or terminal output. Object keys should use
incoming/{import_id}/source.xls or source.xlsx, and
exports/{import_id}/cleaned-events.xlsx and issues.xlsx.

## Required evidence before calling the migration complete

Run Python tests, lint, formatting and mypy plus `npm run check:neon`.
The configuration type check is not a frontend build or a live-service test.
A real development-branch smoke test must exercise actual managed authentication,
private upload/read, unchanged source bytes, processing, both workbook outputs,
blocked unauthorized downloads, persisted event/planning data and configured
frontend-origin API access. Fake Auth or in-memory Storage cannot establish those
hosted-service results. Vercel readiness remains unverified until then.

Official references:

- https://neon.com/docs/storage/get-started
- https://neon.com/docs/auth/authentication-flow
- https://neon.com/docs/auth/guides/plugins/jwt
