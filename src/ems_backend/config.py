"""Server configuration; no credentials or frontend origins are compiled in."""

import os
from dataclasses import dataclass, field
from urllib.parse import urlparse
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Settings:
    supabase_url: str = ""
    supabase_anon_key: str = field(default="", repr=False)
    supabase_service_role_key: str = field(default="", repr=False)
    cors_origins: tuple[str, ...] = ()
    invite_redirect_url: str = ""
    calendar_timezone: str = "America/Denver"
    max_upload_bytes: int = 3_000_000
    max_uncompressed_bytes: int = 40_000_000
    max_rows: int = 30_000
    max_candidates: int = 2_000

    def __post_init__(self) -> None:
        ZoneInfo(self.calendar_timezone)
        if self.max_upload_bytes < 1 or self.max_uncompressed_bytes < 1:
            raise ValueError("Upload limits must be positive")
        for url in (self.supabase_url, *self.cors_origins, self.invite_redirect_url):
            if not url:
                continue
            parsed = urlparse(url)
            local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
            if not parsed.hostname or (
                parsed.scheme != "https" and not (local and parsed.scheme == "http")
            ):
                raise ValueError("Use HTTPS URLs (HTTP is allowed for localhost development)")
        if "*" in self.cors_origins:
            raise ValueError("Explicit CORS origins are required")

    @property
    def configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_anon_key)

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            supabase_url=os.getenv("SUPABASE_URL", "").rstrip("/"),
            supabase_anon_key=os.getenv("SUPABASE_ANON_KEY", ""),
            supabase_service_role_key=os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""),
            cors_origins=tuple(
                x.strip().rstrip("/") for x in os.getenv("CORS_ORIGINS", "").split(",") if x.strip()
            ),
            invite_redirect_url=os.getenv("INVITE_REDIRECT_URL", ""),
            calendar_timezone=os.getenv("CALENDAR_TIMEZONE", "America/Denver"),
            max_upload_bytes=int(os.getenv("MAX_UPLOAD_BYTES", "3000000")),
        )
