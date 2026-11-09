import pytest


@pytest.fixture(autouse=True)
def local_log(tmp_path, monkeypatch):
    monkeypatch.setenv("EMS_LOG_DIR", str(tmp_path / "logs"))
