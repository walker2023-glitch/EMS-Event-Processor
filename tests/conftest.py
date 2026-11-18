import tkinter as tk

import pytest


@pytest.fixture(autouse=True)
def local_log(tmp_path, monkeypatch):
    monkeypatch.setenv("EMS_LOG_DIR", str(tmp_path / "logs"))


@pytest.fixture(scope="session")
def tk_runtime():
    # Repeated Tcl initialization intermittently fails on Windows Python 3.12.
    # Share only the interpreter; each test still gets its own application window.
    root = tk.Tk()
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def ui_root(tk_runtime):
    root = tk.Toplevel(tk_runtime)
    yield root
    # Application.poll schedules itself; do not leave a deleted Tcl callback for
    # the next test's event loop. Worker tests wait for completion before teardown.
    for callback in root.tk.call("after", "info"):
        root.after_cancel(callback)
    root.destroy()
