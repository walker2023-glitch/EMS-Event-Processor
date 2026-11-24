"""Supabase HTTP boundary. Data and storage use the caller's JWT, including RLS."""

from typing import Any, Protocol
from urllib.parse import quote

import httpx

from .config import Settings

JSON = dict[str, Any]


class BackendError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        self.status, self.code, self.message = status, code, message
        super().__init__(message)


class Gateway(Protocol):
    def user(self, token: str) -> JSON: ...
    def rows(
        self,
        token: str,
        table: str,
        filters: list[tuple[str, str]],
        limit: int = 50,
        offset: int = 0,
    ) -> JSON: ...
    def rpc(self, token: str, name: str, params: JSON) -> Any: ...
    def put(self, token: str, path: str, content: bytes, mime: str) -> None: ...
    def get(self, token: str, path: str) -> bytes: ...
    def invite(self, email: str, redirect: str) -> None: ...


class SupabaseGateway:
    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self.settings = settings
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(45, connect=10), follow_redirects=False
        )

    def close(self) -> None:
        self.client.close()

    def request(self, method: str, path: str, token: str, **kwargs: Any) -> httpx.Response:
        if not self.settings.configured:
            raise BackendError(503, "not_configured", "The backend is not configured.")
        headers = {"apikey": self.settings.supabase_anon_key, "Authorization": "Bearer " + token}
        headers.update(kwargs.pop("headers", {}))
        try:
            response = self.client.request(
                method, self.settings.supabase_url + path, headers=headers, **kwargs
            )
        except httpx.HTTPError:
            raise BackendError(
                503, "upstream_unavailable", "The data service is unavailable. Retry later."
            ) from None
        if response.is_error:
            # Never relay upstream errors, SQL, tokens, email addresses, or signed URLs.
            try:
                error = response.json()
                code = error.get("code", "")
                storage_status = str(error.get("statusCode", ""))
            except ValueError:
                code = ""
                storage_status = ""
            if response.status_code == 401:
                raise BackendError(401, "unauthorized", "Sign in with a valid access token.")
            if response.status_code == 403 or code == "42501":
                raise BackendError(403, "forbidden", "Your account cannot perform this action.")
            if response.status_code == 404 or code == "P0002":
                raise BackendError(404, "not_found", "The requested record was not found.")
            if (
                response.status_code == 409
                or storage_status == "409"
                or code in {"23505", "40001", "P0001"}
            ):
                raise BackendError(
                    409,
                    "conflict",
                    "Refresh the preview and resolve all duplicates before approving.",
                )
            if code in {"22023", "23514", "22P02", "22007", "22008"}:
                raise BackendError(422, "invalid_request", "The supplied values are invalid.")
            raise BackendError(
                503, "upstream_failure", "The data service could not complete the request."
            )
        return response

    def user(self, token: str) -> JSON:
        return dict(self.request("GET", "/auth/v1/user", token).json())

    def rows(
        self,
        token: str,
        table: str,
        filters: list[tuple[str, str]],
        limit: int = 50,
        offset: int = 0,
    ) -> JSON:
        params = [
            ("select", "*"),
            ("order", "created_at.asc,id.asc"),
            ("limit", str(limit)),
            ("offset", str(offset)),
            *filters,
        ]
        response = self.request(
            "GET", "/rest/v1/" + table, token, params=params, headers={"Prefer": "count=exact"}
        )
        total = response.headers.get("content-range", "*/0").split("/")[-1]
        return {"items": response.json(), "total": int(total), "limit": limit, "offset": offset}

    def rpc(self, token: str, name: str, params: JSON) -> Any:
        return self.request("POST", "/rest/v1/rpc/" + name, token, json=params).json()

    def put(self, token: str, path: str, content: bytes, mime: str) -> None:
        self.request(
            "POST",
            "/storage/v1/object/ems-private/" + quote(path, safe="/"),
            token,
            content=content,
            headers={"Content-Type": mime, "x-upsert": "false"},
        )

    def get(self, token: str, path: str) -> bytes:
        return self.request(
            "GET", "/storage/v1/object/authenticated/ems-private/" + quote(path, safe="/"), token
        ).content

    def invite(self, email: str, redirect: str) -> None:
        key = self.settings.supabase_service_role_key
        if not key:
            raise BackendError(
                503,
                "invitations_not_configured",
                "The server invitation service is not configured.",
            )
        self.request(
            "POST",
            "/auth/v1/invite",
            key,
            json={"email": email},
            params={"redirect_to": redirect} if redirect else {},
        )
