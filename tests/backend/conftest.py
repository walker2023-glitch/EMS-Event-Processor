"""Real PostgreSQL/RLS; Auth confirmation and Storage bytes are local substitutes."""

import os
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse, urlunparse
from uuid import uuid4

import pytest

psycopg = pytest.importorskip("psycopg")
from psycopg import sql  # noqa: E402
from psycopg.types.json import Jsonb  # noqa: E402

from ems_backend.gateway import BackendError  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


class LocalSupabase:
    """Use the shipped SQL with an authenticated PG role, never owner privileges.

    Bearer tokens are fictional user UUIDs in this test substitute only. Production
    always validates tokens with Supabase Auth's /user endpoint. No test identity
    bypass exists in production code. Storage bytes are kept in a private dict;
    every read/write first checks the real storage.objects RLS policy.
    """

    def __init__(self, dsn, owner):
        self.dsn, self.owner = dsn, owner
        self.objects = {}
        self.invited = {}

    @contextmanager
    def connection(self, token):
        with psycopg.connect(self.dsn) as connection:
            connection.execute("set local role authenticated")
            connection.execute("select set_config('request.jwt.claim.sub',%s,true)", (token,))
            yield connection

    def user(self, token):
        try:
            row = self.owner.execute(
                "select id,email,email_confirmed_at from auth.users where id=%s", (token,)
            ).fetchone()
        except psycopg.Error:
            row = None
        if not row:
            raise BackendError(401, "unauthorized", "Invalid fictional access token")
        return {
            "id": str(row[0]),
            "email": row[1],
            "email_confirmed_at": str(row[2]) if row[2] else None,
        }

    def rows(self, token, table, filters, limit=50, offset=0):
        conditions, params = [], []
        operators = {"eq": "=", "gte": ">=", "lte": "<="}
        for column, value in filters:
            op, argument = value.split(".", 1)
            conditions.append(
                sql.SQL("{} {} %s").format(sql.Identifier(column), sql.SQL(operators[op]))
            )
            params.append(argument)
        condition = sql.SQL(" and ").join(conditions) if conditions else sql.SQL("true")
        with self.connection(token) as conn:
            query = sql.SQL("select count(*) from public.{} where {}").format(
                sql.Identifier(table), condition
            )
            total = conn.execute(query, params).fetchone()[0]
            query = sql.SQL(
                "select to_jsonb(t) from public.{} t where {} "
                "order by created_at,id limit %s offset %s"
            ).format(sql.Identifier(table), condition)
            rows = [r[0] for r in conn.execute(query, [*params, limit, offset]).fetchall()]
        return {"items": rows, "total": total, "limit": limit, "offset": offset}

    def rpc(self, token, name, params):
        args = sql.SQL(",").join(sql.SQL("{}=>%s").format(sql.Identifier(k)) for k in params)
        query = sql.SQL("select public.{}({})").format(sql.Identifier(name), args)
        try:
            with self.connection(token) as conn:
                return conn.execute(
                    query, [Jsonb(v) if isinstance(v, (dict, list)) else v for v in params.values()]
                ).fetchone()[0]
        except psycopg.Error as exc:
            code = exc.sqlstate
            status = (
                403
                if code == "42501"
                else 404
                if code == "P0002"
                else 409
                if code in {"40001", "23505", "P0001"}
                else 422
            )
            raise BackendError(
                status, "database_rejected", "Database rejected the request"
            ) from exc

    def put(self, token, path, content, mime):
        try:
            with self.connection(token) as conn:
                conn.execute(
                    "insert into storage.objects(bucket_id,name) values('ems-private',%s)", (path,)
                )
        except psycopg.Error as exc:
            raise BackendError(
                409 if exc.sqlstate == "23505" else 403,
                "storage_rejected",
                "Storage rejected request",
            ) from exc
        self.objects[path] = content

    def get(self, token, path):
        with self.connection(token) as conn:
            allowed = conn.execute(
                "select name from storage.objects where bucket_id='ems-private' and name=%s",
                (path,),
            ).fetchone()
        if not allowed:
            raise BackendError(404, "not_found", "Private file not accessible")
        return self.objects[path]

    def invite(self, email, redirect):
        identifier = str(uuid4())
        self.owner.execute("insert into auth.users(id,email) values(%s,%s)", (identifier, email))
        self.invited[email] = identifier


@pytest.fixture(scope="session")
def postgres_database():
    dsn = os.environ.get("EMS_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Set EMS_TEST_DATABASE_URL to the disposable local PostgreSQL service")
    parsed = urlparse(dsn)
    if parsed.hostname not in {"127.0.0.1", "localhost", "postgres"}:
        raise RuntimeError("Integration tests require a disposable local PostgreSQL host")
    identifier = "ems_test_" + uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as server:
        server.execute(sql.SQL("create database {}").format(sql.Identifier(identifier)))
    test_dsn = urlunparse(parsed._replace(path="/" + identifier))
    with psycopg.connect(test_dsn, autocommit=True) as conn:
        conn.execute((Path(__file__).parent / "bootstrap.sql").read_text())
        conn.execute((ROOT / "supabase/migrations/202611190001_ems_backend.sql").read_text())
    yield test_dsn
    with psycopg.connect(dsn, autocommit=True) as server:
        server.execute(sql.SQL("drop database {} with (force)").format(sql.Identifier(identifier)))


@pytest.fixture
def local_service(postgres_database):
    # Fresh schema contents for each scenario; no user or production database is used.
    with psycopg.connect(postgres_database, autocommit=True) as conn:
        conn.execute(
            "truncate public.profiles,public.invitations,public.imports,public.events,"
            "public.import_events,public.resource_requests,public.issues,"
            "public.calendar_items,public.export_files,auth.users,storage.objects cascade"
        )
        service = LocalSupabase(postgres_database, conn)
        users = {}
        for role in ("viewer", "editor", "admin"):
            identifier = str(uuid4())
            email = role + "@example.invalid"
            conn.execute("insert into public.invitations(email,role) values(%s,%s)", (email, role))
            conn.execute(
                "insert into auth.users(id,email,email_confirmed_at) values(%s,%s,now())",
                (identifier, email),
            )
            conn.execute("update public.profiles set is_active=true where id=%s", (identifier,))
            conn.execute("update public.invitations set accepted_at=now() where email=%s", (email,))
            users[role] = identifier
        yield service, users, conn
