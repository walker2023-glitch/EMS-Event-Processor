import hashlib
import io
from pathlib import Path
from uuid import uuid4

import openpyxl
import pytest
from fastapi.testclient import TestClient
from psycopg import errors

from ems_backend.app import create_app
from ems_backend.config import Settings
from ems_backend.gateway import BackendError
from ems_backend.processing import XLS, XLSX
from tests.fixture_factory import setup_rows, write_rows

FIXTURES = Path(__file__).parents[1] / "fixtures"


@pytest.fixture
def api(local_service):
    service, users, connection = local_service
    settings = Settings(
        supabase_url="https://fictional.supabase.co",
        supabase_anon_key="fictional",
        cors_origins=("https://frontend.example.invalid",),
    )
    with TestClient(create_app(settings, service)) as client:
        yield client, service, users, connection


def header(users, role="admin"):
    return {"Authorization": "Bearer " + users[role]}


def upload(api, content=None, extension="xlsx"):
    client, service, users, conn = api
    content = (
        content if content is not None else (FIXTURES / f"sanitized_setup.{extension}").read_bytes()
    )
    response = client.post(
        "/imports",
        headers=header(users),
        files={"file": ("worksheet." + extension, content, XLSX if extension == "xlsx" else XLS)},
    )
    assert response.status_code == 201, response.text
    return response.json()


def preview_approve(api, record):
    client, service, users, conn = api
    response = client.get(f"/imports/{record['id']}/preview", headers=header(users))
    assert response.status_code == 200, response.text
    preview = response.json()
    response = client.post(
        f"/imports/{record['id']}/approve",
        headers=header(users),
        json={"preview_version": preview["preview_version"]},
    )
    assert response.status_code == 200, response.text
    return preview, response.json()


@pytest.mark.parametrize("extension", ["xls", "xlsx"])
def test_invite_upload_preview_approve_calendar_download_end_to_end(api, extension):
    client, service, users, conn = api
    invitation = client.post(
        "/auth/invitations",
        headers=header(users),
        json={"email": "new-editor@example.invalid", "role": "editor"},
    )
    assert invitation.status_code == 201, invitation.text
    new_user = service.invited["new-editor@example.invalid"]
    users["invited"] = new_user
    assert client.get("/auth/me", headers=header(users, "invited")).status_code == 401
    conn.execute("update auth.users set email_confirmed_at=now() where id=%s", (new_user,))
    assert (
        client.post("/auth/accept-invitation", headers=header(users, "invited")).status_code == 200
    )
    assert client.get("/auth/me", headers=header(users, "invited")).json()["role"] == "editor"
    source = FIXTURES / f"sanitized_setup.{extension}"
    before = (hashlib.sha256(source.read_bytes()).digest(), source.stat().st_mtime_ns)
    record = upload(api, extension=extension)
    assert record["status"] == "preview_ready"
    assert conn.execute("select count(*) from public.events").fetchone()[0] == 0
    assert service.get(users["admin"], record["storage_path"]) == source.read_bytes()
    preview, approved = preview_approve(api, record)
    assert preview["counts"] == {"new": 3, "changed": 0, "unchanged": 0, "possible_duplicate": 0}
    assert len(preview["issues"]) == 2
    assert approved["events_applied"] == 3
    event = client.get("/events", headers=header(users, "viewer")).json()["items"][0]
    response = client.patch(
        "/events/" + event["id"] + "/planning",
        headers=header(users, "invited"),
        json={"planning_notes": "Fictional planning note", "planning_status": "Ready"},
    )
    assert response.status_code == 200, response.text
    resources = client.get("/resources", headers=header(users, "viewer")).json()
    assert resources["total"] == 5
    calendar = client.get(
        "/calendar-items",
        params={"view": "month", "anchor": "2026-11-10", "import_id": record["id"]},
        headers=header(users, "viewer"),
    ).json()
    assert calendar["total"] == 3
    assert all(c["item_type"] == "event" for c in calendar["items"])
    files = client.get(
        "/exports", params={"import_id": record["id"]}, headers=header(users, "viewer")
    ).json()["items"]
    assert {f["file_type"] for f in files} == {"organized_workbook", "issues_workbook"}
    for f in files:
        response = client.get("/exports/" + f["id"] + "/download", headers=header(users, "viewer"))
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "private, no-store"
        book = openpyxl.load_workbook(io.BytesIO(response.content))
        assert book.sheetnames == (
            ["Issues"]
            if f["file_type"] == "issues_workbook"
            else ["Events", "Equipment Requests", "Equipment Summary"]
        )
        if f["file_type"] == "organized_workbook":
            event_rows = list(book["Events"].values)
            source_column = event_rows[0].index("Source File")
            assert all(row[source_column] == "worksheet." + extension for row in event_rows[1:])
            assert sorted(row[4] for row in list(book["Equipment Summary"].values)[1:]) == [
                4,
                5,
                12,
            ]
        book.close()
    assert (hashlib.sha256(source.read_bytes()).digest(), source.stat().st_mtime_ns) == before
    assert client.get("/issues", headers=header(users, "viewer")).json()["total"] == 2
    assert (
        conn.execute(
            "select count(*) from public.invitations where email=%s and accepted_at is not null",
            ("new-editor@example.invalid",),
        ).fetchone()[0]
        == 1
    )


def test_idempotent_reupload_and_approval(api):
    client, service, users, conn = api
    record = upload(api)
    preview, result = preview_approve(api, record)
    assert upload(api)["id"] == record["id"]
    assert (
        client.post(
            f"/imports/{record['id']}/approve",
            headers=header(users),
            json={"preview_version": preview["preview_version"]},
        ).json()
        == result
    )
    for table, count in [
        ("events", 3),
        ("resource_requests", 5),
        ("calendar_items", 3),
        ("issues", 2),
        ("export_files", 2),
    ]:
        assert conn.execute("select count(*) from public." + table).fetchone()[0] == count


def test_changed_import_preserves_planning_and_manual_calendar(api, tmp_path):
    client, service, users, conn = api
    record = upload(api)
    preview_approve(api, record)
    event = client.get("/events", headers=header(users)).json()["items"][0]
    client.patch(
        "/events/" + event["id"] + "/planning",
        headers=header(users, "editor"),
        json={
            "planning_notes": "Keep this note",
            "recommendations": "Keep recommendation",
            "planning_status": "Ready",
        },
    )
    cal = client.get("/calendar-items", headers=header(users)).json()["items"][0]
    body = {
        k: cal[k]
        for k in [
            "event_id",
            "item_type",
            "title",
            "start_at",
            "end_at",
            "all_day",
            "location",
            "description",
            "status",
        ]
    }
    body["title"] = "Website-owned calendar title"
    assert (
        client.patch(
            "/calendar-items/" + cal["id"], headers=header(users, "editor"), json=body
        ).status_code
        == 200
    )
    rows, breaks = setup_rows()
    for row in rows:
        if len(row) > 7 and row[7] == 2:
            row[7] = 6
    changed = write_rows(tmp_path / "changed.xlsx", rows, breaks).read_bytes()
    new = upload(api, changed)
    preview, _ = preview_approve(api, new)
    assert preview["counts"]["changed"] == 1
    assert preview["counts"]["unchanged"] == 2
    after = client.get("/events/" + event["id"], headers=header(users)).json()
    assert (after["planning_notes"], after["recommendations"], after["planning_status"]) == (
        "Keep this note",
        "Keep recommendation",
        "Ready",
    )
    assert client.get("/events", headers=header(users)).json()["total"] == 3
    assert client.get("/resources", headers=header(users)).json()["total"] == 5
    assert client.get("/resources?include_history=true", headers=header(users)).json()["total"] > 5
    assert client.get("/calendar-items", headers=header(users)).json()["total"] == 3
    assert (
        conn.execute(
            "select title from public.calendar_items where id=%s", (cal["id"],)
        ).fetchone()[0]
        == "Website-owned calendar title"
    )


def test_stale_preview_and_atomic_rollback(api, tmp_path):
    client, service, users, conn = api
    record = upload(api)
    preview_approve(api, record)
    rows, breaks = setup_rows()
    rows.append([])
    second = upload(api, write_rows(tmp_path / "second.xlsx", rows, breaks).read_bytes())
    preview = client.get(f"/imports/{second['id']}/preview", headers=header(users)).json()
    conn.execute(
        "update public.events set fingerprint='changed-by-concurrent-import' "
        "where id=(select id from public.events limit 1)"
    )
    response = client.post(
        f"/imports/{second['id']}/approve",
        headers=header(users),
        json={"preview_version": preview["preview_version"]},
    )
    assert response.status_code == 409
    assert (
        conn.execute("select status from public.imports where id=%s", (second["id"],)).fetchone()[0]
        == "preview_ready"
    )
    assert (
        conn.execute(
            "select count(*) from public.import_events where import_id=%s", (second["id"],)
        ).fetchone()[0]
        == 0
    )


@pytest.mark.parametrize("role", ["viewer", "editor"])
def test_roles_cannot_bypass_protected_api_or_database(api, role):
    client, service, users, conn = api
    assert (
        client.post(
            "/auth/invitations",
            headers=header(users, role),
            json={"email": "blocked@example.invalid", "role": "admin"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/imports", headers=header(users, role), files={"file": ("fake.xlsx", b"fake", XLSX)}
        ).status_code
        == 403
    )
    with pytest.raises(BackendError) as rejected:
        service.rpc(users[role], "register_import", {"p_filename": "fake.xlsx", "p_hash": "0" * 64})
    assert rejected.value.status == 403
    with pytest.raises(errors.InsufficientPrivilege), service.connection(users[role]) as c:
        c.execute("update public.profiles set role='admin' where id=%s", (users[role],))
    with pytest.raises(errors.InsufficientPrivilege), service.connection(users[role]) as c:
        c.execute(
            "insert into public.imports(original_filename,source_file_hash,"
            "storage_path,uploaded_by) "
            "values('fake.xlsx',%s,'fake',%s)",
            ("0" * 64, users[role]),
        )


def test_viewer_cannot_edit_planning_calendar_or_issues(api):
    client, service, users, conn = api
    record = upload(api)
    preview_approve(api, record)
    event = client.get("/events", headers=header(users)).json()["items"][0]
    assert (
        client.patch(
            "/events/" + event["id"] + "/planning",
            headers=header(users, "viewer"),
            json={"planning_notes": "No"},
        ).status_code
        == 403
    )
    with pytest.raises(BackendError):
        service.rpc(
            users["viewer"],
            "update_planning",
            {"p_id": event["id"], "p_patch": {"planning_notes": "No"}},
        )
    issue = client.get("/issues", headers=header(users)).json()["items"][0]
    assert (
        client.patch(
            "/issues/" + issue["id"], headers=header(users, "editor"), json={"resolved": True}
        ).status_code
        == 403
    )
    assert (
        client.patch(
            "/issues/" + issue["id"], headers=header(users), json={"resolved": True}
        ).json()["resolved"]
        is True
    )


@pytest.mark.parametrize(
    "body,name,mime,status",
    [
        (b"bad", "bad.xlsx", XLSX, 422),
        (b"bad", "bad.xls", XLS, 422),
        (b"bad", "bad.csv", "text/csv", 422),
        (b"", "empty.xlsx", XLSX, 413),
    ],
)
def test_malformed_uploads_fail_safely(api, body, name, mime, status):
    client, service, users, conn = api
    response = client.post("/imports", headers=header(users), files={"file": (name, body, mime)})
    assert response.status_code == status, response.text
    assert conn.execute("select count(*) from public.events").fetchone()[0] == 0


def test_private_storage_and_forged_source_updates(api):
    client, service, users, conn = api
    record = upload(api)
    with pytest.raises(BackendError):
        service.get(users["viewer"], record["storage_path"])
    assert client.get("/exports", headers=header(users, "viewer")).json()["items"] == []
    preview_approve(api, record)
    with pytest.raises(BackendError):
        service.put(
            users["admin"], record["storage_path"], b"overwrite", "application/octet-stream"
        )
    with pytest.raises(errors.InsufficientPrivilege), service.connection(users["admin"]) as c:
        c.execute("update public.events set event_name='forged'")
    with pytest.raises(errors.InsufficientPrivilege), service.connection("") as c:
        c.execute("set local role anon")
        c.execute("select public.register_import(%s,%s)", ("fake.xlsx", "0" * 64))


def test_revoked_expired_and_uninvited_accounts(api):
    client, service, users, conn = api
    for state in ["revoked", "expired"]:
        email = state + "@example.invalid"
        response = client.post(
            "/auth/invitations", headers=header(users), json={"email": email, "role": "viewer"}
        )
        assert response.status_code == 201
        identifier = service.invited[email]
        conn.execute("update auth.users set email_confirmed_at=now() where id=%s", (identifier,))
        if state == "revoked":
            assert (
                client.post(
                    "/auth/invitations/" + response.json()["id"] + "/revoke", headers=header(users)
                ).status_code
                == 200
            )
        else:
            conn.execute(
                "update public.invitations set expires_at=now()-interval '1 second' where email=%s",
                (email,),
            )
        assert (
            client.post(
                "/auth/accept-invitation", headers={"Authorization": "Bearer " + identifier}
            ).status_code
            == 403
        )
    with pytest.raises(errors.InsufficientPrivilege):
        conn.execute(
            "insert into auth.users(id,email) values(%s,%s)",
            (str(uuid4()), "uninvited@example.invalid"),
        )


def test_calendar_types_filters_pagination_and_validation(api):
    client, service, users, conn = api
    record = upload(api)
    preview_approve(api, record)
    event = client.get("/events", headers=header(users)).json()["items"][0]
    for item_type in ["setup", "teardown", "planning_meeting", "resource_task", "follow_up"]:
        body = {
            "event_id": event["id"],
            "item_type": item_type,
            "title": "Fictional task",
            "start_at": "2026-11-06T10:00:00-07:00",
            "end_at": "2026-11-06T11:00:00-07:00",
            "location": "Fictional room",
        }
        response = client.post("/calendar-items", headers=header(users, "editor"), json=body)
        assert response.status_code == 201, response.text
    assert (
        client.get("/calendar-items?view=week&anchor=2026-11-06", headers=header(users)).json()[
            "total"
        ]
        == 8
    )
    result = client.get(
        "/calendar-items?item_type=resource_task&location=Fictional%20room&limit=1",
        headers=header(users),
    ).json()
    assert result["total"] == 1 and len(result["items"]) == 1
    assert client.get("/calendar-items?limit=101", headers=header(users)).status_code == 422
    assert client.get("/calendar-items?view=month", headers=header(users)).status_code == 422
    assert (
        client.get(
            "/events?date_from=2026-12-01&date_to=2026-01-01", headers=header(users)
        ).status_code
        == 422
    )
    assert client.get("/events?limit=1&offset=1", headers=header(users)).json()["total"] == 3


def test_midnight_calendar_end_is_exclusive(api):
    client, service, users, conn = api
    record = upload(api)
    preview_approve(api, record)
    event = client.get("/events", headers=header(users)).json()["items"][0]
    body = {
        "event_id": event["id"],
        "item_type": "follow_up",
        "title": "Boundary task",
        "start_at": "2026-10-31T12:00:00-06:00",
        "end_at": "2026-11-01T00:00:00-06:00",
    }
    assert client.post("/calendar-items", headers=header(users), json=body).status_code == 201
    assert (
        client.get(
            "/calendar-items?date_from=2026-11-01&date_to=2026-11-01", headers=header(users)
        ).json()["total"]
        == 0
    )


def test_cors_and_profile_management(api):
    client, service, users, conn = api
    response = client.options(
        "/events",
        headers={
            "Origin": "https://frontend.example.invalid",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert response.headers["access-control-allow-origin"] == "https://frontend.example.invalid"
    assert (
        "access-control-allow-origin"
        not in client.get(
            "/health", headers={"Origin": "https://untrusted.example.invalid"}
        ).headers
    )
    assert (
        client.patch(
            "/auth/profiles/" + users["viewer"],
            headers=header(users),
            json={"role": "editor", "is_active": True},
        ).status_code
        == 200
    )
    assert (
        client.patch(
            "/auth/profiles/" + users["admin"],
            headers=header(users),
            json={"role": "viewer", "is_active": False},
        ).status_code
        == 409
    )


def test_duplicate_candidates_require_explicit_decisions_and_preserve_both(api, tmp_path):
    client, service, users, conn = api
    rows, breaks = setup_rows()
    for row in rows:
        if len(row) > 22 and isinstance(row[22], int):
            row[22] = None
        if len(row) > 6 and row[6] == "Second Gathering":
            row[6] = "Example Gathering"
    record = upload(api, write_rows(tmp_path / "duplicates.xlsx", rows, breaks).read_bytes())
    preview = client.get(f"/imports/{record['id']}/preview", headers=header(users)).json()
    assert preview["counts"]["possible_duplicate"] == 2
    response = client.post(
        f"/imports/{record['id']}/approve",
        headers=header(users),
        json={"preview_version": preview["preview_version"]},
    )
    assert response.status_code == 409
    assert conn.execute("select count(*) from public.events").fetchone()[0] == 0
    resolutions = [
        {"candidate_id": r["candidate"]["candidate_id"], "action": "create"}
        for r in preview["items"]
        if r["classification"] == "possible_duplicate"
    ]
    response = client.post(
        f"/imports/{record['id']}/approve",
        headers=header(users),
        json={"preview_version": preview["preview_version"], "resolutions": resolutions},
    )
    assert response.status_code == 200, response.text
    assert conn.execute("select count(*) from public.events").fetchone()[0] == 3
    assert (
        conn.execute(
            "select count(*) from public.issues where issue_type='Possible duplicate'"
        ).fetchone()[0]
        == 2
    )
    assert conn.execute("select count(*) from public.calendar_items").fetchone()[0] == 3


def test_transaction_rolls_back_earlier_candidates_on_late_failure(api):
    client, service, users, conn = api
    record = upload(api)
    conn.execute(
        "update public.imports set payload=jsonb_set(payload,"
        "'{candidates,1,resources,0,quantity}',%s::jsonb) where id=%s",
        ('"not-a-number"', record["id"]),
    )
    preview = client.get(f"/imports/{record['id']}/preview", headers=header(users)).json()
    response = client.post(
        f"/imports/{record['id']}/approve",
        headers=header(users),
        json={"preview_version": preview["preview_version"]},
    )
    assert response.status_code == 422, response.text
    for table in ["events", "resource_requests", "issues", "calendar_items", "import_events"]:
        assert conn.execute("select count(*) from public." + table).fetchone()[0] == 0
    assert (
        conn.execute("select status from public.imports where id=%s", (record["id"],)).fetchone()[0]
        == "preview_ready"
    )


def test_concurrent_approvals_are_idempotent(api):
    from concurrent.futures import ThreadPoolExecutor

    client, service, users, conn = api
    record = upload(api)
    preview = client.get(f"/imports/{record['id']}/preview", headers=header(users)).json()

    def approve_once():
        return service.rpc(
            users["admin"],
            "approve_import",
            {"p_id": record["id"], "p_version": preview["preview_version"], "p_resolutions": []},
        )

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(lambda _: approve_once(), range(2)))
    assert results[0] == results[1]
    assert conn.execute("select count(*) from public.events").fetchone()[0] == 3
    assert conn.execute("select count(*) from public.calendar_items").fetchone()[0] == 3


def test_inactive_account_and_expired_exports_are_denied(api):
    client, service, users, conn = api
    record = upload(api)
    preview_approve(api, record)
    export = client.get("/exports", headers=header(users)).json()["items"][0]
    conn.execute(
        "update public.export_files set expires_at=now()-interval '1 day' where id=%s",
        (export["id"],),
    )
    assert (
        client.get(
            "/exports/" + export["id"] + "/download", headers=header(users, "viewer")
        ).status_code
        == 404
    )
    conn.execute("update public.profiles set is_active=false where id=%s", (users["viewer"],))
    assert client.get("/events", headers=header(users, "viewer")).status_code == 403
    with pytest.raises(BackendError):
        service.rpc(
            users["viewer"], "query_calendar", {"p_filters": {}, "p_limit": 50, "p_offset": 0}
        )


def test_request_limit_and_validation_do_not_echo_user_input(api):
    client, service, users, conn = api
    response = client.post(
        "/imports", headers=header(users), files={"file": ("huge.xlsx", b"X" * 3_100_000, XLSX)}
    )
    assert response.status_code == 413, response.text
    response = client.post(
        "/auth/invitations",
        headers=header(users),
        json={"email": "private-invalid-address", "role": "bad"},
    )
    assert response.status_code == 422
    assert "private-invalid-address" not in response.text


@pytest.mark.parametrize("strength", ["reservation", "normalized"])
def test_matching_falls_back_when_stronger_identifiers_are_missing(api, tmp_path, strength):
    client, service, users, conn = api
    original = upload(api)
    preview_approve(api, original)
    identifiers = {r[0] for r in conn.execute("select id from public.events")}
    rows, breaks = setup_rows()
    for row in rows:
        if len(row) > 22 and isinstance(row[22], int):
            if strength == "normalized" or row[22] >= 90000:
                row[22] = None
    record = upload(api, write_rows(tmp_path / "fallback.xlsx", rows, breaks).read_bytes())
    preview, _ = preview_approve(api, record)
    assert preview["counts"]["possible_duplicate"] == 0
    assert {r[0] for r in conn.execute("select id from public.events")} == identifiers


def test_existing_possible_matches_require_an_allowed_target(api, tmp_path):
    client, service, users, conn = api
    original = upload(api)
    preview_approve(api, original)
    rows, breaks = setup_rows()
    for row in rows:
        if len(row) > 22 and isinstance(row[22], int):
            row[22] += 50000
        if len(row) > 13 and row[13] == "Example Contact 555-0100":
            row[13] = "Different Contact 555-0199"
    record = upload(api, write_rows(tmp_path / "ambiguous.xlsx", rows, breaks).read_bytes())
    preview = client.get(f"/imports/{record['id']}/preview", headers=header(users)).json()
    ambiguous = [i for i in preview["items"] if i["classification"] == "possible_duplicate"]
    assert len(ambiguous) == 3
    resolutions = [
        {
            "candidate_id": i["candidate"]["candidate_id"],
            "action": "match",
            "event_id": i["possible_matches"][0],
        }
        for i in ambiguous
    ]
    wrong = [dict(x) for x in resolutions]
    wrong[0]["event_id"] = str(uuid4())
    response = client.post(
        f"/imports/{record['id']}/approve",
        headers=header(users),
        json={"preview_version": preview["preview_version"], "resolutions": wrong},
    )
    assert response.status_code == 422, response.text
    response = client.post(
        f"/imports/{record['id']}/approve",
        headers=header(users),
        json={"preview_version": preview["preview_version"], "resolutions": resolutions},
    )
    assert response.status_code == 200, response.text
    assert client.get("/events", headers=header(users)).json()["total"] == 3
    assert client.get("/calendar-items", headers=header(users)).json()["total"] == 3


def test_auto_calendar_updates_same_item_when_reliable_event_time_changes(api, tmp_path):
    client, service, users, conn = api
    record = upload(api)
    preview_approve(api, record)
    prior = {str(r[0]): r[1] for r in conn.execute("select id,start_at from public.calendar_items")}
    rows, breaks = setup_rows()
    for row in rows:
        if len(row) > 2 and row[2] == "8:00 AM":
            row[2] = "8:15 AM"
    record = upload(api, write_rows(tmp_path / "times.xlsx", rows, breaks).read_bytes())
    preview_approve(api, record)
    after = {str(r[0]): r[1] for r in conn.execute("select id,start_at from public.calendar_items")}
    assert prior.keys() == after.keys()
    assert all(prior[k].minute == 0 and after[k].minute == 15 for k in prior)


def test_optional_seed_is_guarded_and_contains_fictional_data(api):
    client, service, users, conn = api
    seed = (Path(__file__).resolve().parents[2] / "supabase/seed.sql").read_text()
    with pytest.raises(errors.RaiseException):
        conn.execute(seed)
    conn.execute("rollback")
    conn.execute("set ems.allow_fictional_seed='on'")
    conn.execute(seed)
    assert (
        conn.execute(
            "select count(*) from public.events where event_name='Fictional Planning Example'"
        ).fetchone()[0]
        == 1
    )
    assert (
        conn.execute(
            "select count(*) from public.profiles "
            "where email like 'fictional-%@example.invalid' and not is_active"
        ).fetchone()[0]
        == 3
    )
