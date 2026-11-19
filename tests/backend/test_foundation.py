import io
import zipfile

import httpx
import pytest
from fastapi.testclient import TestClient

from ems_backend.app import create_app
from ems_backend.config import Settings
from ems_backend.gateway import BackendError, SupabaseGateway
from ems_backend.processing import XLSX, validate


def test_health_openapi_and_missing_configuration():
    with TestClient(create_app(Settings())) as client:
        assert client.get("/health").json()["configured"] is False
        schema = client.get("/openapi.json").json()
        assert "/imports/{import_id}/approve" in schema["paths"]
        assert schema["paths"]["/imports"]["post"]["security"]
        assert client.get("/events").status_code == 401
        response = client.get("/events", headers={"Authorization": "Bearer fictional"})
        assert response.status_code == 503


@pytest.mark.parametrize("url", ["http://external.example.invalid", "file:///tmp/data", "*"])
def test_configuration_rejects_unsafe_urls(url):
    with pytest.raises(ValueError):
        Settings(supabase_url=url)


def test_credentials_are_not_in_configuration_repr():
    assert "fictional-secret" not in repr(Settings(supabase_service_role_key="fictional-secret"))


def test_expansion_and_macro_workbooks_are_rejected():
    for name in ["xl/vbaProject.bin", "padding.xml"]:
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as book:
            book.writestr("xl/workbook.xml", "<workbook/>")
            book.writestr("[Content_Types].xml", "<Types/>")
            book.writestr(name, b"X" * 1000)
        with pytest.raises(BackendError):
            validate(stream.getvalue(), "test.xlsx", XLSX, Settings(max_uncompressed_bytes=900))


def test_supabase_transport_uses_user_jwt_for_data_and_service_key_only_for_invites():
    seen = []

    def response(request):
        seen.append(request)
        return httpx.Response(200, json={"id": "fictional"}, headers={"Content-Range": "0-0/1"})

    client = httpx.Client(transport=httpx.MockTransport(response))
    gateway = SupabaseGateway(
        Settings(
            supabase_url="https://fictional.supabase.co",
            supabase_anon_key="fictional-anon",
            supabase_service_role_key="fictional-service",
        ),
        client,
    )
    gateway.user("fictional-user-jwt")
    gateway.rpc("fictional-user-jwt", "preview_import", {"p_id": "fictional"})
    gateway.put(
        "fictional-user-jwt", "fictional/source.xls", b"fictional", "application/octet-stream"
    )
    gateway.invite("test@example.invalid", "https://frontend.example.invalid/invite")
    assert [r.headers["authorization"] for r in seen] == ["Bearer fictional-user-jwt"] * 3 + [
        "Bearer fictional-service"
    ]
    assert all(r.headers["apikey"] == "fictional-anon" for r in seen)


@pytest.mark.parametrize(
    "status,body,expected",
    [
        (403, {}, 403),
        (400, {"code": "42501"}, 403),
        (400, {"code": "40001"}, 409),
        (500, {"message": "private SQL details"}, 503),
    ],
)
def test_upstream_errors_do_not_leak_details(status, body, expected):
    service = SupabaseGateway(
        Settings(supabase_url="https://fictional.supabase.co", supabase_anon_key="fictional"),
        httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(status, json=body))
        ),
    )
    with pytest.raises(BackendError) as error:
        service.rpc("fictional-user-jwt", "preview_import", {})
    assert error.value.status == expected
    assert "private SQL" not in str(error.value)
