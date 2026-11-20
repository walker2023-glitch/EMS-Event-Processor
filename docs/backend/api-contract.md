# EMS Planner frontend API contract

Use the separately hosted frontend with this API; no frontend components or design
are supplied. `/openapi.json` is the authoritative machine-readable contract,
including request and typed response schemas, enums, required fields and parameter
limits. `/docs` provides an interactive client. All examples below use fictional
IDs and data. Configure the API base URL in the frontend's own environment.

## Connecting and authentication

1. Configure the frontend Supabase client with the project URL and its public
   anon/publishable key. Never give it the service-role key.
2. An admin calls `POST /auth/invitations` with the recipient's email and role.
   Supabase sends its invitation email to the configured frontend callback.
3. At the callback, let the Supabase SDK establish the session using the configured
   callback flow. With a token-hash email template, use
   `supabase.auth.verifyOtp({token_hash, type: 'invite'})`; with the SDK's standard
   callback flow, use that flow's session/code exchange. Do not log callback
   tokens or URLs. Set a password with `supabase.auth.updateUser` if needed.
4. Send the resulting **access token** to `POST /auth/accept-invitation`. The
   backend/DB check the confirmed Auth user and the stored invitation, activate
   the profile and consume the invitation. A confirmed email alone cannot join.
5. Read `GET /auth/me`. The browser must still handle backend 403 responses if a
   role changes. Sign-in, password reset, logout and session refresh use Supabase
   Auth's SDK, not custom password endpoints in this API.

```js
// Documentation example only; integrate with your existing frontend/session layer.
async function emsApi(path, options = {}) {
  const { data: { session } } = await supabase.auth.getSession();
  const headers = new Headers(options.headers);
  headers.set('Authorization', `Bearer ${session.access_token}`);
  if (options.body && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }
  const response = await fetch(`${API_BASE_URL}${path}`, { ...options, headers });
  if (!response.ok) throw { status: response.status, ...(await response.json()) };
  return response;
}
```

Use HTTPS outside localhost. Tokens go only in the `Authorization: Bearer ...`
header, never in query strings. Do not manually set multipart Content-Type;
`fetch` must add its boundary. CORS allows only configured exact origins, the
Authorization/Content-Type headers, and GET/POST/PATCH/OPTIONS methods. It exposes
Content-Disposition for downloads. Browser cookies are not used for API auth.
CORS is not an authorization boundary; direct requests still need valid roles.

## Roles

| Operation | Viewer | Editor | Admin |
| --- | --- | --- | --- |
| Read approved imports, events, resources, notes, issues, calendar and exports | Yes | Yes | Yes |
| Edit planning fields and internal calendar items | No | Yes | Yes |
| Invite/revoke users, manage roles, upload/preview/approve imports, resolve issues | No | No | Yes |
| Read original/private preapproval files | No | No | Yes |
| Overwrite original files or delete history | No | No | No public endpoint |

The API and database RPCs enforce the same permissions. Direct table writes are
revoked, including for authenticated admins. Role changes go through an admin RPC;
users cannot set their own role through metadata or a direct table update.

## Shared conventions

- UUID path parameters, ISO `YYYY-MM-DD` dates, ISO times, and timestamps with
  explicit timezone offsets. Imported wall times use `CALENDAR_TIMEZONE`.
- List envelopes are `{ "items": [...], "total": 3, "limit": 50, "offset": 0 }`.
  `limit` defaults to 50, range 1–100. `offset` defaults to 0, range 0–100000.
  `total` counts all matching accessible records before pagination. There is no
  cursor. Advance offset by limit until offset + items.length reaches total.
- Ordinary lists sort by created_at then UUID ascending; calendar lists sort by
  start_at then UUID, with undated items last. Separate page reads are not one
  transaction; refresh the list after an import or edit.
- Unspecified optional fields are null; planning notes/recommendations are strings
  and default to `""`. Unknown request-body fields are rejected.
- Event-name and location filters on `/events` use exact case-sensitive equality.
  Calendar event-name filtering is a case-insensitive normalized substring;
  calendar location and status filters are exact.
- Source event fields cannot be PATCHed. Planning status values are
  `Not reviewed`, `In progress`, `Ready`, `Complete`, `On hold`.
- Original filenames are sanitized to a basename. File paths are server-generated.

## Endpoint reference

Every endpoint except `/health` and OpenAPI/documentation requires a verified
bearer access token and an active profile, except invitation acceptance which
exists specifically to activate an invited confirmed account.

| Method and path | Role | Request | Successful response |
| --- | --- | --- | --- |
| `GET /health` | Public | None | 200 `{status: "ok", configured: boolean, version: "0.1.0"}`; no secret values or DB probe. |
| `POST /auth/invitations` | Admin | JSON `email`, `role` | 201 `InvitationView`: id, email, role, expires_at, created_by/at, accepted_at, revoked_at. Email delivery is delegated to Supabase. |
| `POST /auth/invitations/{invitation_id}/revoke` | Admin | No body | 200 `{id, revoked: true}`; accepted invitations cannot be revoked this way. Deactivate the account instead. |
| `POST /auth/accept-invitation` | Confirmed invited user | No body | 200 `ProfileView`; repeated acceptance by an active user returns the existing profile. |
| `GET /auth/me` | Any active user | None | 200 `ProfileView`: id, display_name, email, role, is_active, created_at, updated_at. |
| `GET /auth/profiles` | Admin | limit, offset | 200 page of profiles. |
| `PATCH /auth/profiles/{user_id}` | Admin | JSON `role`, optional `is_active` (defaults true) | 200 profile. Last active admin is protected. |
| `POST /imports` | Admin | Multipart `file` only | 201 `ImportView`, usually preview_ready; identical bytes return the existing preview_ready/approved import. |
| `GET /imports` | Any active user | limit, offset | 200 import page. Non-admins see approved imports only. |
| `GET /imports/{import_id}` | Any active user | UUID | 200 import metadata/status; inaccessible records return 404. |
| `GET /imports/{import_id}/preview` | Admin | UUID | 200 `PreviewView`; 409 when not ready. |
| `POST /imports/{import_id}/approve` | Admin | `Approval` JSON below | 200 `{import_id, status: "approved", events_applied}`; repeated approval returns the same stored result. |
| `GET /events` | Any active user | date_from, date_to (inclusive), event_name, location, planning_status, data_quality_status, import_id, limit, offset | 200 event page. import_id selects the event's latest source_import_id. |
| `GET /events/{event_id}` | Any active user | UUID | 200 `EventView`. |
| `PATCH /events/{event_id}/planning` | Editor/admin | At least one of planning_status, planning_notes, recommendations | 200 event. Omitted fields are unchanged; null is rejected. Use `""` to clear text. Notes/recommendations max 20000 characters. |
| `GET /resources` | Any active user | event_id, import_id, include_history (default false), limit, offset | 200 resource page. import_id is each resource row's source import, not all imports mentioning the event. |
| `GET /issues` | Any active user | event_id, import_id, resolved, limit, offset | 200 issue page with source_data provenance and resolution metadata. |
| `PATCH /issues/{issue_id}` | Admin | `{ "resolved": true }` or false | 200 issue; resolved_by/at set by the database. |
| `GET /calendar-items` | Any active user | Calendar query parameters below | 200 calendar page. |
| `POST /calendar-items` | Editor/admin | Complete `CalendarWrite` body below | 201 calendar item. |
| `PATCH /calendar-items/{item_id}` | Editor/admin | Complete `CalendarWrite` body; UUID/event_id/item_type must identify the same existing item | 200 item. Missing item gives 404. Source linkage and generated flag cannot be changed. |
| `GET /exports` | Any active user | import_id, limit, offset | 200 `ExportView` page: id, import_id, file_type, filename, created_at, expires_at. |
| `GET /exports/{export_id}/download` | Any active user with access | UUID, Authorization header | 200 binary XLSX, Content-Disposition filename, private/no-store caching; 404 if inaccessible or expired. |

`ImportView` includes id, original_filename, SHA-256 source_file_hash, storage_path,
status, uploaded_by/at, approved_by/at, error_summary, result, expires_at and
created_at/updated_at. Its private preview payload is not returned by these API
responses. Status moves uploaded → processing → preview_ready → approved; a
processing failure records failed and a safe error_summary. Re-upload retries a
failed import without replacing the original object.

`EventView` includes internal id, source_request_id/reservation_id, event_name,
event_date, start_time/end_time, location, contact_or_group, source_import_id,
source_sheet/row/page, original_request_text, data_quality_status, planning_status,
planning_notes, recommendations, created_at/updated_at. IDs from Excel are exposed
as strings consistently across `.xls` and `.xlsx`.

`ResourceView` includes id, event_id, description/category, quantity (number or
null), source_text, source_import_id, is_current, created_at/updated_at. In JSON the
full names are `resource_description` and `resource_category`. Old resource rows
are marked non-current on change, retained for history, and excluded by default.

`CalendarView` adds id, is_generated, user_modified, created_from_import_id and
created_at/updated_at to the write fields. Automatically generated event items
may have null start/end if the source date is missing; unbounded agenda queries
can display them as needing review. Manual writes require an explicit start.

## Upload, preview and approval

```js
const form = new FormData();
form.append('file', selectedFile);
const imported = await (await emsApi('/imports', {method: 'POST', body: form})).json();
const preview = await (await emsApi(`/imports/${imported.id}/preview`)).json();
// Present all classifications/issues and let the admin decide before approval.
const result = await (await emsApi(`/imports/${imported.id}/approve`, {
  method: 'POST', body: JSON.stringify({
    preview_version: preview.preview_version,
    resolutions: []
  })
})).json();
```

Uploads accept `.xls`/`.xlsx`, a matching Excel MIME or application/octet-stream,
and validated workbook content. Default file limit is 3 MB; ZIP expansion is
capped at 40 MB, 3000 ZIP members, 30000 source rows and 2000 candidate events.
Worksheet columns are capped at 256. XML entity declarations and XLSX VBA projects
are rejected. Macros are never executed. Use smaller reports or a separately sized
backend for large inputs. These bounds do not make Vercel deployment verified.

Processing is synchronous in this first slice. Show an indeterminate busy state
while POST runs; do not invent progress percentages. Persisted import statuses can
also be read concurrently. There is no durable background queue or cancellation.

Preview response shape:

```json
{
  "import_id": "30000000-0000-4000-8000-000000000001",
  "preview_version": "a 32-character opaque revision from the server",
  "counts": {"new": 1, "changed": 0, "unchanged": 0, "possible_duplicate": 0},
  "processing_counts": {"events": 1, "resource_requests": 2, "summary_rows": 2, "issues": 0},
  "items": [{
    "candidate": {
      "candidate_id": "processor occurrence identifier",
      "source": {"event_name": "Fictional Gathering", "event_date": "2026-11-20"},
      "resources": [], "calendar": [], "match_keys": [], "fingerprint": "opaque"
    },
    "classification": "new", "matched_event_id": null, "possible_matches": [],
    "within_file_collision": false, "existing_snapshot": []
  }],
  "issues": []
}
```

This example abbreviates SourceEvent fields; generated OpenAPI specifies every
required nullable field. Treat candidate_id, match_keys, fingerprint and revision
as opaque. Preview issues retain the processor's original workbook column names,
such as `Issue Type`, `Description`, `Source Row` and `Related Event ID`.

Matching checks Book ID/request identifier plus occurrence date first, then
reservation identifier plus date, then normalized name/date/location/contact and
start time. Row-based processor IDs are **not** used as cross-file identities.
Multiple matches, collisions within a file, incomplete identity, or same-name/date
neighbors without a reliable match become possible_duplicate. Similar names alone
never silently merge events. Recurring dates remain separate occurrences.

Every possible_duplicate needs one decision:

```json
{
  "preview_version": "USE_THE_SERVER_VALUE",
  "resolutions": [
    {"candidate_id": "candidate-a", "action": "create"},
    {"candidate_id": "candidate-b", "action": "match", "event_id": "40000000-0000-4000-8000-000000000001"},
    {"candidate_id": "candidate-c", "action": "skip"}
  ]
}
```

A match target must be in possible_matches. Two candidates cannot overwrite the
same target in a batch. Decisions are permitted only for ambiguous candidates;
the server rejects unknown/duplicate decision IDs. Approval recomputes matching
under a database lock. A 409 means refresh the preview and review it again, not
blindly retry an old decision. Concurrent approval of the same import is idempotent.
Unresolved ambiguity rolls back the entire approval. Explicitly retained/matched
ambiguous records create database review issues.

Imported source fields and current resources update together; planning notes,
status, recommendations and manually edited calendar fields are preserved. There
is no approval option to replace planning fields. Use their dedicated PATCH API.
No events absent from a newer workbook are automatically deleted or canceled.

## Calendar queries and writes

`view=agenda` is the default. Optional date_from/date_to are inclusive local calendar
dates. Items ending exactly at the lower bound are excluded (end times are
exclusive); zero-duration items at the bound are included. Without a range,
undated generated events are included. `view=month` or
`view=week` requires `anchor=YYYY-MM-DD`; do not also supply explicit date bounds.
Weeks run Monday–Sunday. Calendar timestamps are timezone-aware and queries use
the configured source timezone.

All views additionally accept event_name, location, item_type, planning_status,
data_quality_status, import_id, limit and offset. import_id includes events linked
to that historical import, including manually added items for those events.

Complete manual calendar body:

```json
{
  "event_id": "40000000-0000-4000-8000-000000000001",
  "item_type": "planning_meeting",
  "title": "Fictional setup review",
  "start_at": "2026-11-20T09:00:00-07:00",
  "end_at": "2026-11-20T09:30:00-07:00",
  "all_day": false,
  "location": "Example Hall",
  "description": "Discuss the approved layout",
  "status": "Not reviewed"
}
```

item_type is event, setup, teardown, planning_meeting, resource_task or follow_up.
Title max 300, location max 1000, description max 20000 characters. end_at is
optional/null and must not precede start_at. Manual timestamps require offsets.
PATCH uses this complete body, not a partial merge-patch.

Approval creates one generated event item per occurrence and updates it on
re-import. The current parser has reservation and event times but **no reliable
explicit setup/teardown intervals**. Reservation times are not reinterpreted as
setup/teardown; those items can be added manually. Missing event times become an
all-day item when a date exists. An ambiguous overnight end is left unset.

## Downloads and errors

Find export UUIDs through GET /exports?import_id=... and fetch with Authorization:

```js
const files = await (await emsApi(`/exports?import_id=${imported.id}`)).json();
const response = await emsApi(`/exports/${files.items[0].id}/download`);
const blob = await response.blob();
// Save with your existing download UI; Content-Disposition contains the filename.
```

Workbooks describe the original cleaned source snapshot. They do not include
website planning fields, later matching decisions, skipped-candidate exclusions,
or duplicate-resolution issues added to the database after approval. Review those
through the preview/issues API. The issues workbook exists only when the parser
found source issues. File links are authenticated API calls, not public URLs.

API error envelope:

```json
{"error":{"code":"validation_error","message":"Check the supplied fields.","fields":[{"path":["body","role"],"type":"literal_error"}]}}
```

| Status | Meaning and frontend action |
| --- | --- |
| 401 | Missing/invalid/expired token or unconfirmed email. Refresh the Supabase session or sign in. |
| 403 | Inactive account or insufficient role. Do not retry as another role automatically. |
| 404 | Unknown/inaccessible record, expired export, or not-yet-approved export for a non-admin. |
| 409 | Stale/busy import, ambiguous matching without decisions, invitation conflict, or last-admin protection. Refresh and review. |
| 413 | Empty/oversized upload or workbook processing limit. Explain the limit; do not retry the same bytes indefinitely. |
| 422 | Invalid UUID/date/body/MIME/workbook, unsupported field, timezone-less manual timestamp, or invalid database constraint. Show safe message/field paths. |
| 500 | Unexpected backend failure, safe message only. |
| 503 | Supabase/invitation configuration missing, provider unavailable, or another safe upstream failure. Retry later or contact the administrator. |

Framework 404/405 responses use the same envelope with code http_error. CORS
preflight failures are standard middleware 400 responses and may be plain text.
Error field lists never echo input values. Do not depend on SQL error text or a
particular English error message; use HTTP status and the stable API error code.
