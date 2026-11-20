"""Real HTTP vertical slice on a disposable PostgreSQL database; fictional data only.

Auth email confirmation and Storage bytes use tests.backend's documented local
substitute. PostgreSQL tables, RLS, import transactions, parser and exports are real.
This is a development command, never a production server or authentication mode.
"""

import hashlib
import json
import os
import socket
import threading
import time
from pathlib import Path
from urllib.parse import urlparse, urlunparse
from uuid import uuid4

import httpx
import psycopg
import uvicorn
from psycopg import sql

from ems_backend.app import create_app
from ems_backend.config import Settings
from ems_backend.processing import XLS, XLSX


def main():
    from tests.backend.conftest import LocalSupabase

    dsn = os.environ["EMS_TEST_DATABASE_URL"]
    parsed = urlparse(dsn)
    if parsed.hostname not in {"127.0.0.1", "localhost", "postgres"}:
        raise RuntimeError("Use a disposable local PostgreSQL instance")
    database = "ems_http_smoke_" + uuid4().hex
    root = Path(__file__).resolve().parents[1]
    with psycopg.connect(dsn, autocommit=True) as owner:
        owner.execute(sql.SQL("create database {}").format(sql.Identifier(database)))
    local_dsn = urlunparse(parsed._replace(path="/" + database))
    server, worker, listener = None, None, None
    try:
        with psycopg.connect(local_dsn, autocommit=True) as owner:
            owner.execute((root / "tests/backend/bootstrap.sql").read_text())
            owner.execute((root / "supabase/migrations/202611190001_ems_backend.sql").read_text())
            admin = str(uuid4())
            owner.execute(
                "insert into public.invitations(email,role) "
                "values('bootstrap@example.invalid','admin')"
            )
            owner.execute(
                "insert into auth.users(id,email,email_confirmed_at) "
                "values(%s,'bootstrap@example.invalid',now())",
                (admin,),
            )
            owner.execute("update public.profiles set is_active=true where id=%s", (admin,))
            service = LocalSupabase(local_dsn, owner)
            settings = Settings(
                supabase_url="https://fictional.supabase.co", supabase_anon_key="fictional"
            )
            app = create_app(settings, service)
            listener = socket.socket()
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False))
            worker = threading.Thread(
                target=server.run, kwargs={"sockets": [listener]}, daemon=True
            )
            worker.start()
            deadline = time.monotonic() + 15
            while not server.started and time.monotonic() < deadline:
                time.sleep(0.05)
            assert server.started, "HTTP server did not start"
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=45) as client:
                headers = {"Authorization": "Bearer " + admin}
                invited = client.post(
                    "/auth/invitations",
                    headers=headers,
                    json={"email": "invited-admin@example.invalid", "role": "admin"},
                )
                assert invited.status_code == 201, invited.text
                identifier = service.invited["invited-admin@example.invalid"]
                # Emulate successful verification of the fictional invitation email.
                owner.execute(
                    "update auth.users set email_confirmed_at=now() where id=%s", (identifier,)
                )
                headers = {"Authorization": "Bearer " + identifier}
                assert client.post("/auth/accept-invitation", headers=headers).status_code == 200
                for extension, mime in [("xlsx", XLSX), ("xls", XLS)]:
                    source = root / f"tests/fixtures/sanitized_setup.{extension}"
                    before = (
                        hashlib.sha256(source.read_bytes()).hexdigest(),
                        source.stat().st_mtime_ns,
                    )
                    response = client.post(
                        "/imports",
                        headers=headers,
                        files={"file": (source.name, source.read_bytes(), mime)},
                    )
                    assert response.status_code == 201, response.text
                    record = response.json()
                    preview = client.get("/imports/" + record["id"] + "/preview", headers=headers)
                    assert preview.status_code == 200, preview.text
                    assert len(preview.json()["items"]) == 3
                    approval = client.post(
                        "/imports/" + record["id"] + "/approve",
                        headers=headers,
                        json={"preview_version": preview.json()["preview_version"]},
                    )
                    assert approval.status_code == 200, approval.text
                    files = client.get(
                        "/exports", params={"import_id": record["id"]}, headers=headers
                    ).json()["items"]
                    assert len(files) == 2
                    for export in files:
                        download = client.get(
                            "/exports/" + export["id"] + "/download", headers=headers
                        )
                        assert download.status_code == 200 and download.content.startswith(b"PK")
                    assert (
                        hashlib.sha256(source.read_bytes()).hexdigest(),
                        source.stat().st_mtime_ns,
                    ) == before
                assert client.get("/events", headers=headers).json()["total"] == 3
                assert client.get("/resources", headers=headers).json()["total"] == 5
                assert client.get("/calendar-items", headers=headers).json()["total"] == 3
                event = client.get("/events", headers=headers).json()["items"][0]
                assert (
                    client.patch(
                        "/events/" + event["id"] + "/planning",
                        headers=headers,
                        json={"planning_notes": "Fictional HTTP smoke note"},
                    ).status_code
                    == 200
                )
                print(
                    json.dumps(
                        {
                            "result": "passed",
                            "transport": "real localhost HTTP",
                            "database": "PostgreSQL with real RLS and shipped migration",
                            "auth_and_storage": "fictional local substitute; no hosted credentials",
                            "formats": ["xls", "xlsx"],
                            "events": 3,
                            "current_resources": 5,
                            "calendar_items": 3,
                            "downloaded_workbooks": 4,
                            "source_hashes_and_mtime": "unchanged",
                        }
                    )
                )
    finally:
        if server:
            server.should_exit = True
        if worker:
            worker.join(timeout=15)
        if listener:
            listener.close()
        with psycopg.connect(dsn, autocommit=True) as owner:
            owner.execute(sql.SQL("drop database {} with (force)").format(sql.Identifier(database)))


if __name__ == "__main__":
    main()
