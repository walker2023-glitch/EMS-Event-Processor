# Backend deployment and operations

The API boundary works independently of frontend design and hosting. The
implementation is tested locally and in repository CI; **no hosted Supabase or
Vercel deployment has been performed**. Production credentials, project approval,
SMTP and the actual frontend callback/origins are external setup requirements.

## Vercel suitability

The API is ASGI/FastAPI; `api/index.py`, `requirements.txt` and `vercel.json` provide
a Python function entry point and rewrites. The backend extra does not import Tk,
and temporary workbooks use the platform's temporary directory. All persistent
state is in Supabase, so no function-local state is assumed to survive requests.

Vercel is a **bounded pilot option**, not a verified production runtime. Excel
libraries are synchronous and may expand files substantially in memory. The
request returns only after parsing/export/storage completes. The sample fixtures
fit, but the original large private workbook is not available for this backend
validation. A platform timeout can leave an import in processing; background work
is not reliable after a serverless function returns. Trial uploads default to
3 MB to stay below common request-body limits. Hosting plans/runtime limits can
change: verify duration, memory, bundle, request and response limits with the
selected Vercel plan. Large preview JSON or generated workbooks may exceed function
response limits even with a small upload. Do not simply raise MAX_UPLOAD_BYTES to
bypass these constraints.

Before choosing Vercel, deploy a development project with secrets in the host's
secret manager and test fictional invite acceptance, both input types, representative
file sizes, preview/approval, re-import, downloads and concurrent users. Set the
Python version to a supported 3.11/3.12 runtime. `maxDuration: 60` in vercel.json is
an upper request, not proof the selected plan grants it. Inspect logs with access
tokens and personal/source data redacted.

## Safer backend host for full reports

Run the same API as a long-running Python service on a managed container/Python
host with explicitly sized CPU/memory and a persistent request worker lifetime:

```sh
python -m pip install -e '.[backend]'
python -m uvicorn ems_backend.app:app --host 0.0.0.0 --port 8000
```

Provide the same server environment variables and point the frontend's API base
URL at this host. Supabase and the HTTP contract remain the same. Use HTTPS at the
reverse proxy, disable body/token logging, restrict origins, set a request-body
limit, and add infrastructure rate limits for authenticated upload/invitation
routes. Scale workers only after load tests. The advisory approval lock protects
cross-worker matching; it does not bound aggregate parser memory. A durable queue
with isolated processing workers is the next step if large reports or concurrent
uploads exceed synchronous capacity. That queue is not implemented in this slice.

## Recovery and retention

- Originals are never overwritten. Generated files use distinct immutable paths.
  A failed upload/parse records failed; re-uploading identical bytes retries the
  same import and verifies the existing original before proceeding.
- A process killed before failure bookkeeping may leave processing forever. An
  administrator must first establish the worker is dead, then use a controlled
  owner-only SQL maintenance operation to set that import to failed. There is no
  public force-reset route that could race a live worker. Do not approve a stuck
  import or reset an active processing operation.
- Approval is atomic across events, resources, issues, import links and calendar.
  Generated workbook objects are staged privately before approval; metadata and
  preview become visible together. File storage and PostgreSQL are not a single
  distributed transaction. A storage/provider failure can leave unreferenced
  private export objects. Reconciliation/garbage collection is an operator task
  in this first version; never delete an object until all import/export references
  and the original retention requirement have been checked.
- Imports and export metadata default to one year retention. Exports expire for
  users at expires_at. **Physical object deletion is not automated**; originals
  remain privately retained until a reviewed future admin maintenance/deletion
  feature. There is no destructive history-deletion endpoint.
- Resource replacements mark prior rows non-current, retaining their source import.
  Manually edited generated calendar items remain website-owned across re-imports.
  Missing records in a later source are not treated as deletions.

## Backup and restore before production

1. Select a Supabase database backup/PITR plan suitable for the retention policy.
   Confirm auth.users, profiles, invitations, imports, events, resource history,
   issues, calendar, import links and export metadata are included.
2. Back up private Storage objects separately; a PostgreSQL backup does not contain
   the workbook bytes. Preserve bucket names, object paths and retention metadata.
3. Restore into an isolated development project first. Apply/check migrations and
   privileges, verify RLS as viewer/editor/admin, and reconcile object references.
4. Use fictional/restored test accounts to verify invite acceptance, preview,
   transactional approval and downloads. Confirm no public bucket was introduced.
5. Point a development API at the restored project, verify counts/source hashes,
   then follow an approved production cutover. No real restore drill was performed
   in this work because no hosted project/backups were supplied.

## Remaining acceptance checks

Hosted GoTrue invitation emails/session callbacks, actual hosted Storage REST
requests, SMTP delivery, production RLS configuration after migration, Vercel
runtime limits and backup/restore must be verified against a development project.
The local PostgreSQL substitute and transport contract tests cover logic and
request structure, not those hosted services. Continue the existing employee-device
Windows visual/DPI and EMS-staff sample review before operational rollout.
