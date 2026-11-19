"""EMS Planner HTTP API. Identity and permissions are checked on every operation."""

import hashlib
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, File, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .config import Settings
from .gateway import JSON, BackendError, Gateway, SupabaseGateway
from .processing import XLSX, process, safe_filename, validate
from .schemas import (
    ApprovalView,
    CalendarView,
    EventView,
    ExportView,
    ImportView,
    InvitationView,
    IssueView,
    Page,
    PreviewView,
    ProfileView,
    ResourceView,
    RevocationView,
)

Role = Literal["viewer", "editor", "admin"]
ItemType = Literal["event", "setup", "teardown", "planning_meeting", "resource_task", "follow_up"]
security = HTTPBearer(auto_error=False)
logger = logging.getLogger(__name__)


class BodyLimit:
    def __init__(self, app: ASGIApp, limit: int) -> None:
        self.app, self.limit = app, limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        received = 0

        async def bounded_receive() -> Message:
            nonlocal received
            message = await receive()
            received += len(message.get("body", b""))
            if received > self.limit:
                raise StarletteHTTPException(413, "The request exceeds the upload limit.")
            return message

        # Starlette's exception middleware converts errors raised while parsing multipart.
        await self.app(scope, bounded_receive, send)


class SafeErrors:
    """Keep server tracebacks from echoing sensitive validation/source values."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        started = False

        async def tracked_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracked_send)
        except Exception as exc:
            if scope["type"] != "http":
                raise
            logger.error("Unexpected backend failure (%s)", type(exc).__name__)
            if not started:
                response = JSONResponse(
                    {
                        "error": {
                            "code": "internal_error",
                            "message": "The request could not be completed.",
                            "fields": [],
                        }
                    },
                    status_code=500,
                )
                await response(scope, receive, send)


@dataclass
class Actor:
    id: str
    role: str
    token: str = field(repr=False)


def gateway(request: Request) -> Gateway:
    return request.app.state.gateway  # type: ignore[no-any-return]


def bearer(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)]) -> str:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise BackendError(401, "unauthorized", "Sign in with a valid access token.")
    return credentials.credentials


def authenticated(request: Request, token: Annotated[str, Depends(bearer)]) -> Actor:
    user = gateway(request).user(token)
    if not user.get("id") or not user.get("email_confirmed_at"):
        raise BackendError(
            401, "unconfirmed_account", "Confirm the invited email address before continuing."
        )
    rows = gateway(request).rows(token, "profiles", [("id", "eq." + str(user["id"]))], 1)["items"]
    if not rows or not rows[0]["is_active"]:
        raise BackendError(
            403, "inactive_account", "An active invitation and account are required."
        )
    return Actor(str(user["id"]), str(rows[0]["role"]), token)


Active = Annotated[Actor, Depends(authenticated)]


def require(actor: Actor, *roles: str) -> None:
    if actor.role not in roles:
        raise BackendError(403, "forbidden", "Your account cannot perform this action.")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Invitation(StrictModel):
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    role: Role


class ProfilePatch(StrictModel):
    role: Role
    is_active: bool = True


class PlanningPatch(StrictModel):
    planning_status: (
        Literal["Not reviewed", "In progress", "Ready", "Complete", "On hold"] | None
    ) = None
    planning_notes: str | None = Field(default=None, max_length=20000)
    recommendations: str | None = Field(default=None, max_length=20000)

    @model_validator(mode="after")
    def nonnull(self) -> "PlanningPatch":
        if not self.model_fields_set or any(
            getattr(self, k) is None for k in self.model_fields_set
        ):
            raise ValueError(
                "Supply at least one non-null planning field; use an empty string to clear notes"
            )
        return self


class Resolution(StrictModel):
    candidate_id: str = Field(max_length=150)
    action: Literal["create", "match", "skip"]
    event_id: UUID | None = None

    @model_validator(mode="after")
    def target(self) -> "Resolution":
        if (self.action == "match") != (self.event_id is not None):
            raise ValueError("Only match decisions require an event_id")
        return self


class Approval(StrictModel):
    preview_version: str = Field(min_length=32, max_length=64)
    resolutions: list[Resolution] = Field(default_factory=list, max_length=2000)

    @model_validator(mode="after")
    def unique(self) -> "Approval":
        ids = [r.candidate_id for r in self.resolutions]
        if len(ids) != len(set(ids)):
            raise ValueError("Each candidate can have only one resolution")
        return self


class IssuePatch(StrictModel):
    resolved: bool


class CalendarWrite(StrictModel):
    event_id: UUID
    item_type: ItemType
    title: str = Field(min_length=1, max_length=300)
    start_at: datetime
    end_at: datetime | None = None
    all_day: bool = False
    location: str = Field(default="", max_length=1000)
    description: str = Field(default="", max_length=20000)
    status: Literal["Not reviewed", "In progress", "Ready", "Complete", "On hold"] = "Not reviewed"

    @field_validator("start_at", "end_at")
    @classmethod
    def aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("Times must include an explicit UTC offset")
        return value

    @model_validator(mode="after")
    def ordered(self) -> "CalendarWrite":
        if self.end_at and self.end_at < self.start_at:
            raise ValueError("end_at must not precede start_at")
        return self


class ErrorDetail(BaseModel):
    code: str
    message: str
    fields: list[JSON] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    error: ErrorDetail


def create_app(settings: Settings | None = None, service: Gateway | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    service = service or SupabaseGateway(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
        yield
        if isinstance(service, SupabaseGateway):
            service.close()

    app = FastAPI(
        title="EMS Event Planner Backend",
        version="0.1.0",
        lifespan=lifespan,
        description=(
            "Invite-only shared-workspace API. JWT authentication uses Supabase Auth. "
            "Admin approval commits imports atomically. Desktop behavior is independent."
        ),
        responses={code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 413, 422, 503)},
    )
    app.state.gateway, app.state.settings = service, settings
    app.add_middleware(BodyLimit, limit=settings.max_upload_bytes + 65536)
    app.add_middleware(SafeErrors)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=["Content-Disposition"],
        allow_credentials=False,
    )

    @app.exception_handler(BackendError)
    async def handled(request: Request, exc: BackendError) -> JSONResponse:
        return JSONResponse(
            {"error": {"code": exc.code, "message": exc.message, "fields": []}},
            status_code=exc.status,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            {
                "error": {
                    "code": "request_size" if exc.status_code == 413 else "http_error",
                    "message": str(exc.detail),
                    "fields": [],
                }
            },
            status_code=exc.status_code,
        )

    @app.exception_handler(RequestValidationError)
    async def invalid(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Validation errors must not echo bearer tokens, emails or workbook contents.
        fields = [{"path": [str(x) for x in e["loc"]], "type": e["type"]} for e in exc.errors()]
        return JSONResponse(
            {
                "error": {
                    "code": "validation_error",
                    "message": "Check the supplied fields.",
                    "fields": fields,
                }
            },
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.error("Unexpected backend failure (%s)", type(exc).__name__)
        return JSONResponse(
            {
                "error": {
                    "code": "internal_error",
                    "message": "The request could not be completed.",
                    "fields": [],
                }
            },
            status_code=500,
        )

    @app.get("/health", tags=["System"])
    def health() -> JSON:
        return {"status": "ok", "configured": settings.configured, "version": "0.1.0"}

    @app.get("/auth/me", response_model=ProfileView, tags=["Accounts"])
    def me(request: Request, actor: Active) -> Any:
        return gateway(request).rows(actor.token, "profiles", [("id", "eq." + actor.id)], 1)[
            "items"
        ][0]

    @app.post("/auth/accept-invitation", response_model=ProfileView, tags=["Accounts"])
    def accept(request: Request, token: Annotated[str, Depends(bearer)]) -> Any:
        user = gateway(request).user(token)
        if not user.get("email_confirmed_at"):
            raise BackendError(
                401, "unconfirmed_account", "Confirm the invited email address first."
            )
        return gateway(request).rpc(token, "accept_invitation", {})

    @app.post(
        "/auth/invitations", response_model=InvitationView, status_code=201, tags=["Accounts"]
    )
    def invite(body: Invitation, request: Request, actor: Active) -> Any:
        require(actor, "admin")
        record = gateway(request).rpc(
            actor.token, "begin_invitation", {"p_email": body.email.casefold(), "p_role": body.role}
        )
        try:
            gateway(request).invite(body.email, settings.invite_redirect_url)
        except BackendError:
            gateway(request).rpc(actor.token, "revoke_invitation", {"p_id": record["id"]})
            raise
        return record

    @app.post(
        "/auth/invitations/{invitation_id}/revoke", response_model=RevocationView, tags=["Accounts"]
    )
    def revoke(invitation_id: UUID, request: Request, actor: Active) -> Any:
        require(actor, "admin")
        return gateway(request).rpc(actor.token, "revoke_invitation", {"p_id": str(invitation_id)})

    @app.get("/auth/profiles", response_model=Page[ProfileView], tags=["Accounts"])
    def profiles(
        request: Request,
        actor: Active,
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0, le=100000),
    ) -> Any:
        require(actor, "admin")
        return gateway(request).rows(actor.token, "profiles", [], limit, offset)

    @app.patch("/auth/profiles/{user_id}", response_model=ProfileView, tags=["Accounts"])
    def profile(user_id: UUID, body: ProfilePatch, request: Request, actor: Active) -> Any:
        require(actor, "admin")
        return gateway(request).rpc(
            actor.token,
            "set_profile_role",
            {"p_user": str(user_id), "p_role": body.role, "p_active": body.is_active},
        )

    @app.post("/imports", response_model=ImportView, status_code=201, tags=["Imports"])
    def upload(
        request: Request,
        actor: Active,
        file: Annotated[
            UploadFile,
            File(description="One .xls or .xlsx workbook, up to MAX_UPLOAD_BYTES. Admin only."),
        ],
    ) -> Any:
        require(actor, "admin")
        content = file.file.read(settings.max_upload_bytes + 1)
        filename = safe_filename(file.filename)
        extension = validate(content, filename, file.content_type or "", settings)
        record = gateway(request).rpc(
            actor.token,
            "register_import",
            {"p_filename": filename, "p_hash": hashlib.sha256(content).hexdigest()},
        )
        if record["status"] in {"approved", "preview_ready"}:
            return record
        import_id = record["id"]
        gateway(request).rpc(actor.token, "claim_import", {"p_id": import_id})
        try:
            # Immutable path; retries verify an existing object instead of replacing it.
            try:
                gateway(request).put(
                    actor.token,
                    record["storage_path"],
                    content,
                    file.content_type or "application/octet-stream",
                )
            except BackendError as exc:
                if (
                    exc.status != 409
                    or gateway(request).get(actor.token, record["storage_path"]) != content
                ):
                    raise
            result = process(content, extension, settings, record["original_filename"])
            exports = []
            for kind, data in result.pop("exports"):
                path = f"{import_id}/exports/{uuid4()}/{kind}.xlsx"
                gateway(request).put(actor.token, path, data, XLSX)
                exports.append(
                    {
                        "file_type": kind,
                        "storage_path": path,
                        "filename": "organized.xlsx"
                        if kind == "organized_workbook"
                        else "organized_issues.xlsx",
                    }
                )
            return gateway(request).rpc(
                actor.token,
                "finish_import",
                {"p_id": import_id, "p_payload": result, "p_exports": exports},
            )
        except Exception:
            try:
                gateway(request).rpc(actor.token, "fail_import", {"p_id": import_id})
            except Exception:
                logger.error("Could not record failed import %s", import_id)
            raise

    @app.get("/imports", response_model=Page[ImportView], tags=["Imports"])
    def imports(
        request: Request,
        actor: Active,
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0, le=100000),
    ) -> Any:
        return gateway(request).rows(actor.token, "imports", [], limit, offset)

    @app.get("/imports/{import_id}", response_model=ImportView, tags=["Imports"])
    def get_import(import_id: UUID, request: Request, actor: Active) -> Any:
        rows = gateway(request).rows(actor.token, "imports", [("id", "eq." + str(import_id))], 1)[
            "items"
        ]
        if not rows:
            raise BackendError(404, "not_found", "Import not found.")
        return rows[0]

    @app.get("/imports/{import_id}/preview", response_model=PreviewView, tags=["Imports"])
    def preview(import_id: UUID, request: Request, actor: Active) -> Any:
        require(actor, "admin")
        return gateway(request).rpc(actor.token, "preview_import", {"p_id": str(import_id)})

    @app.post("/imports/{import_id}/approve", response_model=ApprovalView, tags=["Imports"])
    def approve(import_id: UUID, body: Approval, request: Request, actor: Active) -> Any:
        require(actor, "admin")
        return gateway(request).rpc(
            actor.token,
            "approve_import",
            {
                "p_id": str(import_id),
                "p_version": body.preview_version,
                "p_resolutions": body.model_dump(mode="json")["resolutions"],
            },
        )

    @app.get("/events", response_model=Page[EventView], tags=["Events"])
    def events(
        request: Request,
        actor: Active,
        date_from: date | None = None,
        date_to: date | None = None,
        location: str | None = Query(None, max_length=1000),
        event_name: str | None = Query(None, max_length=300),
        planning_status: str | None = Query(None, max_length=50),
        data_quality_status: str | None = Query(None, max_length=300),
        import_id: UUID | None = None,
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0, le=100000),
    ) -> Any:
        filters = [
            (k, "eq." + str(v))
            for k, v in {
                "location": location,
                "event_name": event_name,
                "planning_status": planning_status,
                "data_quality_status": data_quality_status,
                "source_import_id": import_id,
            }.items()
            if v is not None
        ]
        if date_from:
            filters.append(("event_date", "gte." + date_from.isoformat()))
        if date_to:
            filters.append(("event_date", "lte." + date_to.isoformat()))
        if date_from and date_to and date_from > date_to:
            raise BackendError(422, "invalid_range", "date_from must not follow date_to.")
        return gateway(request).rows(actor.token, "events", filters, limit, offset)

    @app.get("/events/{event_id}", response_model=EventView, tags=["Events"])
    def event(event_id: UUID, request: Request, actor: Active) -> Any:
        rows = gateway(request).rows(actor.token, "events", [("id", "eq." + str(event_id))], 1)[
            "items"
        ]
        if not rows:
            raise BackendError(404, "not_found", "Event not found.")
        return rows[0]

    @app.patch("/events/{event_id}/planning", response_model=EventView, tags=["Events"])
    def planning(event_id: UUID, body: PlanningPatch, request: Request, actor: Active) -> Any:
        require(actor, "editor", "admin")
        return gateway(request).rpc(
            actor.token,
            "update_planning",
            {"p_id": str(event_id), "p_patch": body.model_dump(exclude_unset=True)},
        )

    @app.get("/resources", response_model=Page[ResourceView], tags=["Resources"])
    def resources(
        request: Request,
        actor: Active,
        event_id: UUID | None = None,
        import_id: UUID | None = None,
        include_history: bool = False,
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0, le=100000),
    ) -> Any:
        filters = [
            (k, "eq." + str(v))
            for k, v in {"event_id": event_id, "source_import_id": import_id}.items()
            if v is not None
        ]
        if not include_history:
            filters.append(("is_current", "eq.true"))
        return gateway(request).rows(actor.token, "resource_requests", filters, limit, offset)

    @app.get("/issues", response_model=Page[IssueView], tags=["Issues"])
    def issues(
        request: Request,
        actor: Active,
        import_id: UUID | None = None,
        event_id: UUID | None = None,
        resolved: bool | None = None,
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0, le=100000),
    ) -> Any:
        filters = [
            (k, "eq." + str(v).lower())
            for k, v in {"import_id": import_id, "event_id": event_id, "resolved": resolved}.items()
            if v is not None
        ]
        return gateway(request).rows(actor.token, "issues", filters, limit, offset)

    @app.patch("/issues/{issue_id}", response_model=IssueView, tags=["Issues"])
    def resolve(issue_id: UUID, body: IssuePatch, request: Request, actor: Active) -> Any:
        require(actor, "admin")
        return gateway(request).rpc(
            actor.token, "resolve_issue", {"p_id": str(issue_id), "p_resolved": body.resolved}
        )

    @app.get("/calendar-items", response_model=Page[CalendarView], tags=["Calendar"])
    def calendar(
        request: Request,
        actor: Active,
        view: Literal["month", "week", "agenda"] = "agenda",
        anchor: date | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        event_name: str | None = Query(None, max_length=300),
        location: str | None = Query(None, max_length=1000),
        item_type: ItemType | None = None,
        planning_status: str | None = Query(None, max_length=50),
        data_quality_status: str | None = Query(None, max_length=300),
        import_id: UUID | None = None,
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0, le=100000),
    ) -> Any:
        if view != "agenda":
            if anchor is None or date_from or date_to:
                raise BackendError(
                    422,
                    "invalid_range",
                    "Month/week views require anchor and do not accept explicit date bounds.",
                )
            if view == "week":
                date_from = anchor - timedelta(days=anchor.weekday())
                date_to = date_from + timedelta(days=6)
            else:
                date_from = anchor.replace(day=1)
                date_to = (date_from.replace(day=28) + timedelta(days=4)).replace(
                    day=1
                ) - timedelta(days=1)
        if date_from and date_to and date_from > date_to:
            raise BackendError(422, "invalid_range", "date_from must not follow date_to.")
        return gateway(request).rpc(
            actor.token,
            "query_calendar",
            {
                "p_filters": {
                    "date_from": str(date_from) if date_from else None,
                    "date_to": str(date_to) if date_to else None,
                    "timezone": settings.calendar_timezone,
                    "event_name": event_name,
                    "location": location,
                    "item_type": item_type,
                    "planning_status": planning_status,
                    "data_quality_status": data_quality_status,
                    "import_id": str(import_id) if import_id else None,
                },
                "p_limit": limit,
                "p_offset": offset,
            },
        )

    @app.post("/calendar-items", response_model=CalendarView, status_code=201, tags=["Calendar"])
    def calendar_create(body: CalendarWrite, request: Request, actor: Active) -> Any:
        require(actor, "editor", "admin")
        return gateway(request).rpc(
            actor.token, "save_calendar", {"p_id": None, "p_data": body.model_dump(mode="json")}
        )

    @app.patch("/calendar-items/{item_id}", response_model=CalendarView, tags=["Calendar"])
    def calendar_update(item_id: UUID, body: CalendarWrite, request: Request, actor: Active) -> Any:
        require(actor, "editor", "admin")
        return gateway(request).rpc(
            actor.token,
            "save_calendar",
            {"p_id": str(item_id), "p_data": body.model_dump(mode="json")},
        )

    @app.get("/exports", response_model=Page[ExportView], tags=["Files"])
    def exports(
        request: Request,
        actor: Active,
        import_id: UUID | None = None,
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0, le=100000),
    ) -> Any:
        return gateway(request).rows(
            actor.token,
            "export_files",
            [("import_id", "eq." + str(import_id))] if import_id else [],
            limit,
            offset,
        )

    @app.get(
        "/exports/{export_id}/download",
        tags=["Files"],
        response_class=Response,
        responses={200: {"content": {XLSX: {"schema": {"type": "string", "format": "binary"}}}}},
    )
    def download(export_id: UUID, request: Request, actor: Active) -> Response:
        rows = gateway(request).rows(
            actor.token, "export_files", [("id", "eq." + str(export_id))], 1
        )["items"]
        if not rows:
            raise BackendError(404, "not_found", "Export not found or not yet approved.")
        record = rows[0]
        if datetime.fromisoformat(record["expires_at"].replace("Z", "+00:00")) <= datetime.now(UTC):
            raise BackendError(404, "expired_export", "This export has expired.")
        return Response(
            gateway(request).get(actor.token, record["storage_path"]),
            media_type=XLSX,
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{safe_filename(record["filename"])}"'
                ),
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    return app


app = create_app()
