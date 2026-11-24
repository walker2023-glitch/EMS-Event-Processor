# EMS Event Planner Backend Implementation Plan

## 1. Purpose

Build the backend for a web-based EMS Event Planner. The backend will accept the original EMS Excel workbook, reuse the existing EMS Event Processor logic to clean and interpret it, save approved event data in Supabase, generate internal planning-calendar items, and provide cleaned Excel files for download.

The frontend is being designed separately by another employee. The backend must therefore expose a clear, documented API and must not depend on a particular visual design.

The existing desktop “tinker” application remains available as an offline backup. It must continue to work independently and should not be removed or replaced during this project.

## 2. Product decisions

- The website is the primary workflow.
- The desktop tinker application is the backup workflow.
- Supabase is the hosted database, authentication, and private file-storage platform.
- Users receive an invitation link before creating an account.
- Approved employees and bosses may invite users.
- Users may have different permissions depending on the invitation:
  - `viewer`: can view events, resources, calendar items, notes, and issues.
  - `editor`: can edit planning fields, notes, recommendations, and internal calendar items.
  - `admin`: can manage users, invitations, imports, files, and system settings.
- Planning notes are visible to all users who can access the event.
- The EMS source data remains the source of truth for imported event/resource fields.
- Planning notes, statuses, recommendations, and internal calendar information belong to the website.
- Calendar items are created automatically after an import is reviewed and approved.
- The internal calendar contains events, setup, teardown, planning meetings, resource tasks, and follow-up items.
- Users must be able to download the cleaned workbook and issues workbook.
- Uploaded files and generated files should be retained for one year by default, with administrator deletion available later.

## 3. MVP scope

### Must include

1. Invite-based account creation and sign-in.
2. Role-based access control for viewer, editor, and admin users.
3. EMS `.xls` and `.xlsx` upload.
4. Original-file preservation.
5. Reuse of the existing parser and cleaning logic where practical.
6. Import preview before database changes are committed.
7. Detection of new, changed, unchanged, and possible duplicate events.
8. Approved import into Supabase.
9. Storage of events, resource requests, issues, import history, and planning fields.
10. Automatic creation or update of internal calendar items after approved import.
11. Download of the cleaned workbook and issues workbook.
12. API documentation for the frontend developer.
13. Tests for parsing, import matching, authorization, and calendar-item generation.

### Not required for the first backend version

- Google Calendar or Microsoft Outlook integration.
- Automatic work-order creation in another school website.
- AI-generated recommendations.
- Drag-and-drop calendar editing.
- Complex departmental permissions.
- Public sign-up.
- Destructive deletion of event history.

## 4. Recommended architecture

```text
Frontend
  ↓ HTTPS API
Backend API / upload endpoints
  ├── EMS Excel processing module
  ├── import preview and matching
  ├── permission checks
  ├── calendar-item generation
  └── workbook export
        ↓
Supabase
  ├── Auth
  ├── PostgreSQL database
  ├── private Storage buckets
  └── Row Level Security policies

Existing desktop tinker app
  └── remains an independent offline backup
```

Prefer keeping the Excel-processing code in a reusable Python module. The first deployment may use Vercel’s Python/FastAPI support if the processor fits the runtime limits. Keep the API boundary clean so the processor can move to a separate Python host later without requiring a frontend rewrite.

## 5. Data model

Use migrations rather than creating tables manually in production.

### `profiles`

- `id` — Supabase Auth user ID
- `display_name`
- `email`
- `role` — `viewer`, `editor`, or `admin`
- `is_active`
- `created_at`
- `updated_at`

### `invitations`

- `id`
- `email` or invited-email restriction, if used
- `role`
- `token_hash` or Supabase invitation reference
- `created_by`
- `expires_at`
- `accepted_at`
- `revoked_at`
- `created_at`

### `imports`

- `id`
- `original_filename`
- `source_file_hash`
- `storage_path`
- `status` — `uploaded`, `processing`, `preview_ready`, `approved`, `failed`
- `uploaded_by`
- `uploaded_at`
- `approved_by`
- `approved_at`
- `error_summary`
- `created_at`

### `events`

- `id` — internal UUID
- `source_reservation_id`, when present
- `event_name`
- `event_date`
- `start_time`
- `end_time`
- `location`
- `contact_or_group`
- `source_import_id`
- `source_sheet`
- `source_row`
- `source_page`
- `original_request_text`
- `data_quality_status`
- `planning_status` — default `Not reviewed`
- `planning_notes`
- `recommendations`
- `created_at`
- `updated_at`

### `resource_requests`

- `id`
- `event_id`
- `resource_description`
- `resource_category`, when available
- `quantity`
- `source_text`
- `source_import_id`
- `created_at`
- `updated_at`

### `issues`

- `id`
- `import_id`
- `event_id`, when known
- `issue_type`
- `severity`
- `message`
- `source_sheet`
- `source_row`
- `resolved`
- `resolved_by`
- `resolved_at`

### `calendar_items`

- `id`
- `event_id`
- `item_type` — `event`, `setup`, `teardown`, `planning_meeting`, `resource_task`, or `follow_up`
- `title`
- `start_at`
- `end_at`
- `location`
- `description`
- `status`
- `created_from_import_id`
- `created_at`
- `updated_at`

### `export_files`

- `id`
- `import_id`
- `file_type` — `organized_workbook` or `issues_workbook`
- `storage_path`
- `created_at`
- `expires_at`, if retention is implemented

## 6. Import workflow

1. Authenticated user uploads an `.xls` or `.xlsx` file.
2. Backend validates file type and size.
3. Backend stores the original file in a private bucket.
4. Backend creates an `imports` record.
5. Processor reads the workbook without modifying the original file.
6. Processor creates normalized event, resource, and issue candidates.
7. Backend matches candidates against existing events.
8. Backend returns a preview containing:
   - new events;
   - changed events;
   - unchanged events;
   - possible duplicates;
   - issues;
   - summary counts.
9. User reviews the preview.
10. User approves the import.
11. Backend commits event/resource changes in a transaction.
12. Backend preserves planning fields on existing events unless the user explicitly chooses to replace them.
13. Backend creates or updates internal calendar items.
14. Backend generates the organized and issues workbooks.
15. Backend stores the generated files and returns secure download links.

An import must be idempotent: approving the same file twice must not create duplicate events or duplicate calendar items.

## 7. Matching and duplicate rules

Use the strongest available match key in this order:

1. Source reservation/request ID.
2. Stable source identifier plus event date.
3. Normalized event name, date, location, and contact/group.
4. If no reliable match exists, mark the record as a possible duplicate and require review.

Never silently merge two records merely because their names look similar. Preserve both records and create an issue when confidence is low.

Calendar items must store the internal event ID and import ID so that re-importing can update the existing item instead of creating another one.

## 8. Permissions

Enforce authorization on the backend and in Supabase Row Level Security. Do not rely only on hidden frontend buttons.

- Viewers can read permitted data.
- Editors can modify planning fields and internal calendar items.
- Admins can invite users, change roles, approve imports, manage files, and resolve issues.
- Only admins should be able to permanently delete uploaded files or historical records.

Start with one shared organization/workspace. Design the tables so multiple workspaces could be added later if needed.

## 9. API contract for the frontend

Document endpoints using OpenAPI or an equivalent format. The initial API should include:

- `POST /auth/invitations`
- `GET /auth/me`
- `POST /imports`
- `GET /imports`
- `GET /imports/{id}`
- `GET /imports/{id}/preview`
- `POST /imports/{id}/approve`
- `GET /events`
- `GET /events/{id}`
- `PATCH /events/{id}/planning`
- `GET /resources`
- `GET /issues`
- `PATCH /issues/{id}`
- `GET /calendar-items`
- `POST /calendar-items`
- `PATCH /calendar-items/{id}`
- `GET /exports/{id}/download`

Document request/response examples, validation errors, authorization errors, and pagination/filter behavior so the frontend developer can work independently.

## 10. Internal calendar requirements

The calendar must support filtering by:

- date range;
- event name;
- location;
- calendar-item type;
- planning status;
- import batch;
- data-quality/review status.

The backend should support month, week, and agenda/list queries. The agenda/list response is especially important for meeting preparation.

Initial calendar creation rules should be configurable and clearly documented. At minimum, create an `event` item for each approved event. Create setup and teardown items only when the source data contains reliable setup or teardown times.

## 11. Security and reliability requirements

- Keep Supabase service-role keys on the server only.
- Do not expose private storage buckets publicly.
- Validate file extensions, MIME types, file sizes, and workbook structure.
- Treat uploaded workbook contents as untrusted input.
- Do not execute macros or embedded workbook code.
- Use transactions for imports.
- Log failures without storing unnecessary sensitive data.
- Preserve the original file unchanged.
- Provide safe error messages to users and detailed logs for administrators.
- Add database indexes for dates, locations, statuses, source IDs, and event matching fields.
- Add backup and restore documentation before production use.

## 12. Testing requirements

At minimum, add tests for:

- `.xls` processing;
- `.xlsx` processing;
- malformed or unsupported files;
- source-file preservation;
- event and resource parsing;
- issues generation;
- duplicate and changed-event matching;
- idempotent re-imports;
- preservation of planning notes;
- role-based authorization;
- calendar-item creation and update;
- cleaned workbook and issues workbook downloads;
- API validation and error responses.

Use synthetic test accounts and fictional event data. Do not commit real credentials, production files, or Supabase service-role keys.

## 13. Development phases

### Phase 1 — Backend foundation

- Inspect the existing EMS Event Processor.
- Separate reusable processing logic from desktop UI code if needed.
- Create the backend project and local development instructions.
- Add environment-variable configuration.
- Add Supabase migrations and seed data.
- Add basic health-check endpoint.

### Phase 2 — Authentication and permissions

- Add invite-based account creation.
- Add profile and role management.
- Add backend authorization checks.
- Add Supabase Row Level Security policies.

### Phase 3 — Upload and processing

- Add file upload endpoint.
- Save original files privately.
- Run the processor.
- Return import preview data.
- Add issues and matching results.

### Phase 4 — Approved import and exports

- Add import approval endpoint.
- Save events and resources transactionally.
- Preserve planning fields.
- Generate cleaned and issues workbooks.
- Add secure download endpoints.

### Phase 5 — Internal calendar

- Generate calendar items after approved imports.
- Add calendar filtering and list queries.
- Add editor updates for calendar items.
- Add idempotency tests.

### Phase 6 — Deployment

- Deploy the website/API using Vercel if compatible.
- Configure Supabase production environment.
- Add deployment secrets through the host’s secret manager.
- Test with fictional accounts and sample files.
- Confirm the tinker application still works independently.

## 14. Definition of done for the first vertical slice

The first implementation is complete when an invited test user can:

1. Create an account from an invitation.
2. Sign in.
3. Upload a sample EMS workbook.
4. See processing progress and a preview.
5. Review issues and possible duplicates.
6. Approve the import.
7. See events and resources saved in Supabase.
8. See internal calendar items created automatically.
9. Download the cleaned workbook and issues workbook.
10. Add or edit planning notes if they have editor access.
11. Confirm that a viewer cannot edit protected data.
12. Re-import the same workbook without duplicate events or calendar items.
13. Confirm that the original source workbook remains unchanged.

Codex should not claim completion based only on unit tests. It should also perform an end-to-end test with a fictional Supabase project or a documented local test substitute.
