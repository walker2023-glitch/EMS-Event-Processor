"""Public response schemas for frontend code generation."""

from datetime import date, datetime, time
from typing import Any, Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class ProfileView(BaseModel):
    id: UUID
    display_name: str
    email: str
    role: Literal["viewer", "editor", "admin"]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class InvitationView(BaseModel):
    id: UUID
    email: str
    role: Literal["viewer", "editor", "admin"]
    expires_at: datetime
    accepted_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime
    created_by: UUID | None


class ImportView(BaseModel):
    id: UUID
    original_filename: str
    source_file_hash: str
    storage_path: str
    status: Literal["uploaded", "processing", "preview_ready", "approved", "failed"]
    uploaded_by: UUID
    uploaded_at: datetime
    approved_by: UUID | None
    approved_at: datetime | None
    error_summary: str | None
    result: dict[str, Any] | None
    expires_at: datetime
    created_at: datetime
    updated_at: datetime


class SourceEvent(BaseModel):
    source_request_id: str | None = None
    source_reservation_id: str | None = None
    event_name: str | None
    event_date: date | None
    start_time: time | None
    end_time: time | None
    location: str | None
    contact_or_group: str | None
    source_sheet: str | None
    source_row: int | None
    source_page: int | None
    original_request_text: str | None
    data_quality_status: str | None


class EventView(SourceEvent):
    id: UUID
    source_import_id: UUID
    planning_status: str
    planning_notes: str
    recommendations: str
    created_at: datetime
    updated_at: datetime


class ResourceView(BaseModel):
    id: UUID
    event_id: UUID
    resource_description: str | None
    resource_category: str | None
    quantity: float | None
    source_text: str | None
    source_import_id: UUID
    is_current: bool
    created_at: datetime
    updated_at: datetime


class IssueView(BaseModel):
    id: UUID
    import_id: UUID
    event_id: UUID | None
    issue_type: str | None
    severity: str | None
    message: str | None
    source_sheet: str | None
    source_row: int | None
    source_data: dict[str, Any]
    resolved: bool
    resolved_by: UUID | None
    resolved_at: datetime | None
    created_at: datetime


class CalendarView(BaseModel):
    id: UUID
    event_id: UUID
    item_type: Literal[
        "event", "setup", "teardown", "planning_meeting", "resource_task", "follow_up"
    ]
    title: str
    start_at: datetime | None
    end_at: datetime | None
    all_day: bool
    location: str | None
    description: str | None
    status: str
    is_generated: bool
    user_modified: bool
    created_from_import_id: UUID | None
    created_at: datetime
    updated_at: datetime


class ExportView(BaseModel):
    id: UUID
    import_id: UUID
    file_type: Literal["organized_workbook", "issues_workbook"]
    filename: str
    created_at: datetime
    expires_at: datetime


class CandidateView(BaseModel):
    candidate_id: str
    source: SourceEvent
    match_keys: list[str]
    fingerprint: str
    resources: list[dict[str, Any]]
    calendar: list[dict[str, Any]]


class PreviewItem(BaseModel):
    candidate: CandidateView
    classification: Literal["new", "changed", "unchanged", "possible_duplicate"]
    matched_event_id: UUID | None
    possible_matches: list[UUID]
    within_file_collision: bool
    existing_snapshot: list[dict[str, Any]]


class PreviewView(BaseModel):
    import_id: UUID
    items: list[PreviewItem]
    issues: list[dict[str, Any]]
    counts: dict[str, int]
    processing_counts: dict[str, int]
    preview_version: str


class ApprovalView(BaseModel):
    import_id: UUID
    status: Literal["approved"]
    events_applied: int


class RevocationView(BaseModel):
    id: UUID
    revoked: bool
