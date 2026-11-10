"""Real Tk widgets + real processing; native OS dialogs return controlled paths."""

import time
import tkinter as tk
from pathlib import Path

import openpyxl
import pytest

from ems_event_processor.ui import Application

FIXTURE = Path(__file__).parent / "fixtures" / "sanitized_setup.xlsx"


@pytest.fixture
def ui():
    # A display is a verification prerequisite, not a silently skipped test.
    root = tk.Tk()
    app = Application(root)
    yield root, app
    root.destroy()


def run_until_done(root, app):
    deadline = time.monotonic() + 15
    ticks = 0
    while app.busy and time.monotonic() < deadline:
        root.update()
        ticks += 1
        time.sleep(0.01)
    assert not app.busy, "Background processing did not finish"
    return ticks


def test_ui_choose_save_process_openable_outputs(ui, tmp_path, monkeypatch):
    root, app = ui
    output = tmp_path / "organized.xlsx"
    monkeypatch.setattr(
        "ems_event_processor.ui.filedialog.askopenfilename", lambda **kw: str(FIXTURE)
    )
    monkeypatch.setattr(
        "ems_event_processor.ui.filedialog.asksaveasfilename", lambda **kw: str(output)
    )
    app.choose.invoke()
    assert app.file.get() == str(FIXTURE)
    app.process.invoke()
    assert app.busy and str(app.choose["state"]) == "disabled"
    # A fast fixture may finish during the first Tk update. The gated-worker
    # tests in test_ui_themes.py check responsiveness without a timing race.
    run_until_done(root, app)
    assert "Events: 3" in app.summary.get() and "Issues: 2" in app.summary.get()
    assert "Processing complete" in app.status.get()
    assert app.output == output
    for path in (output, tmp_path / "organized_issues.xlsx"):
        book = openpyxl.load_workbook(path)
        assert book.worksheets[0].max_row > 1
        book.close()


@pytest.mark.parametrize("kind", ["unreadable", "invalid_save"])
def test_ui_error_does_not_claim_success(ui, tmp_path, monkeypatch, kind):
    root, app = ui
    source = FIXTURE if kind == "invalid_save" else tmp_path / "bad.xlsx"
    if kind == "unreadable":
        source.write_text("corrupt")
    output = (
        tmp_path / "missing" / "output.xlsx" if kind == "invalid_save" else tmp_path / "out.xlsx"
    )
    app.selected = source
    monkeypatch.setattr(
        "ems_event_processor.ui.filedialog.asksaveasfilename", lambda **kw: str(output)
    )
    errors = []
    monkeypatch.setattr(
        "ems_event_processor.ui.messagebox.showerror", lambda *a, **k: errors.append(a)
    )
    app.process_file()
    run_until_done(root, app)
    assert errors and "failed" in app.status.get()
    assert app.output is None
    assert str(app.open_folder["state"]) == "disabled"


def test_cancel_dialogs_and_keyboard_widgets(ui, monkeypatch):
    root, app = ui
    monkeypatch.setattr("ems_event_processor.ui.filedialog.askopenfilename", lambda **kw: "")
    app.choose.invoke()
    assert app.selected is None
    assert str(app.process["state"]) == "disabled"
    app.selected = FIXTURE
    monkeypatch.setattr("ems_event_processor.ui.filedialog.asksaveasfilename", lambda **kw: "")
    app.process_file()
    assert not app.busy
    assert app.choose.cget("takefocus") != 0
    root.update()
    assert root.title() == "EMS Event Processor"


def test_ui_unexpected_worker_error_and_close_guard(ui, tmp_path, monkeypatch):
    root, app = ui
    app.selected = FIXTURE
    monkeypatch.setattr(
        "ems_event_processor.ui.filedialog.asksaveasfilename",
        lambda **kw: str(tmp_path / "out.xlsx"),
    )

    def fail(*args):
        raise RuntimeError("sensitive internal detail")

    monkeypatch.setattr("ems_event_processor.ui.process_workbook", fail)
    errors = []
    monkeypatch.setattr(
        "ems_event_processor.ui.messagebox.showerror", lambda *a, **k: errors.append(a)
    )
    monkeypatch.setattr("ems_event_processor.ui.messagebox.showinfo", lambda *a, **k: None)
    app.busy = True
    app.close()
    assert root.winfo_exists()
    app.busy = False
    app.process_file()
    run_until_done(root, app)
    assert errors and "sensitive" not in app.summary.get()
