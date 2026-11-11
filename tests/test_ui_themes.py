"""UI state/theme checks with an actual Tk interpreter and unchanged processor."""

import hashlib
import threading
import time
from pathlib import Path

import openpyxl
import pytest

from ems_event_processor.models import ProcessingResult
from ems_event_processor.ui import Application
from ems_event_processor.ui_theme import PALETTES
from tests.test_ui import run_until_done

FIXTURE = Path(__file__).parent / "fixtures" / "sanitized_setup.xlsx"


@pytest.fixture
def ui(ui_root):
    root = ui_root
    app = Application(root)
    root.update()
    yield root, app


def select(app, monkeypatch, path=FIXTURE):
    monkeypatch.setattr("ems_event_processor.ui.filedialog.askopenfilename", lambda **kw: str(path))
    app.choose.invoke()


def test_initial_state_and_no_file_does_not_prompt_to_save(ui, monkeypatch):
    root, app = ui
    assert app.theme.get() == "light" and app.state == "idle"
    assert app.selected is None and app.output is None
    assert app.filename.get() == "No file selected"
    assert str(app.process["state"]) == "disabled"
    assert str(app.open_folder["state"]) == "disabled"
    assert not app.paths.winfo_ismapped() and not app.metrics.winfo_ismapped()
    assert all(c.get() == "—" for c in app.counts.values())
    calls = []
    monkeypatch.setattr(
        "ems_event_processor.ui.filedialog.asksaveasfilename", lambda **kw: calls.append(kw)
    )
    app.process_file()
    assert not calls and not app.busy
    assert root.title() == "EMS Event Processor"


@pytest.mark.parametrize("extension", [".xls", ".xlsx", ".XLSX"])
def test_selected_filename_and_enabled_process(ui, monkeypatch, tmp_path, extension):
    root, app = ui
    source = tmp_path / ("A selected workbook" + extension)
    source.write_bytes(FIXTURE.read_bytes())
    select(app, monkeypatch, source)
    root.update()
    assert app.selected == source
    assert app.filename.get() == source.name and app.file.get() == str(source)
    assert app.state == "selected"
    assert app.choose["text"] == "Change File"
    assert str(app.process["state"]) == "normal"
    assert app.file_display.winfo_ismapped()


@pytest.mark.parametrize("case", ["csv", "missing", "directory"])
def test_invalid_selection_keeps_processing_disabled(ui, monkeypatch, tmp_path, case):
    root, app = ui
    source = tmp_path / ("file.csv" if case == "csv" else "file.xlsx")
    if case == "directory":
        source.mkdir()
    elif case == "csv":
        source.write_text("not an Excel workbook")
    select(app, monkeypatch, source)
    assert str(app.process["state"]) == "disabled"
    assert app.state == "error" and ".xls" in app.status.get()
    assert str(app.open_folder["state"]) == "disabled"


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_theme_covers_app_fields_buttons_and_status(ui, mode):
    root, app = ui
    (app.light_mode if mode == "light" else app.dark_mode).invoke()
    root.update()
    palette = PALETTES[mode]
    assert app.theme.get() == mode
    assert app.canvas.cget("background") == palette["background"]
    assert root.cget("background") == palette["background"]
    for style, option, expected in [
        ("Card.TFrame", "background", "surface"),
        ("Field.TFrame", "background", "field"),
        ("Metric.TFrame", "background", "field"),
        ("Title.TLabel", "foreground", "text"),
        ("Card.TLabel", "foreground", "text"),
        ("Muted.TLabel", "foreground", "muted"),
        ("EMS.Horizontal.TProgressbar", "background", "primary"),
        ("Success.TLabel", "foreground", "success"),
        ("Warning.TLabel", "foreground", "warning"),
        ("Error.TLabel", "foreground", "error"),
    ]:
        assert app.style.lookup(style, option) == palette[expected]
    assert app.style.lookup("Path.TEntry", "fieldbackground", ("readonly",)) == palette["field"]
    assert app.style.lookup("Primary.TButton", "background", ("disabled",)) == palette["disabled"]
    assert (
        app.style.lookup("Primary.TButton", "foreground", ("disabled",)) == palette["disabled_text"]
    )
    assert str(app.process["state"]) == "disabled"


def test_switching_themes_preserves_selection_and_cancellation(ui, monkeypatch):
    root, app = ui
    select(app, monkeypatch)
    for _ in range(3):
        app.dark_mode.invoke()
        app.light_mode.invoke()
    monkeypatch.setattr("ems_event_processor.ui.filedialog.askopenfilename", lambda **kw: "")
    app.choose.invoke()
    assert app.selected == FIXTURE and app.file.get() == str(FIXTURE)
    assert str(app.process["state"]) == "normal"
    assert app.theme.get() == "light"


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_switch_during_worker_progress_preserves_real_outputs(ui, monkeypatch, tmp_path, mode):
    import ems_event_processor.ui as ui_module

    root, app = ui
    output = tmp_path / "organized.xlsx"
    before = hashlib.sha256(FIXTURE.read_bytes()).digest()
    actual = ui_module.process_workbook
    entered, release = threading.Event(), threading.Event()
    worker_ids = []

    def gated(source, destination, progress):
        worker_ids.append(threading.get_ident())
        progress("Reading the source workbook…")
        entered.set()
        if not release.wait(10):
            raise TimeoutError("Test failed to release the worker")
        return actual(source, destination, progress)

    monkeypatch.setattr(ui_module, "process_workbook", gated)
    monkeypatch.setattr(ui_module.filedialog, "asksaveasfilename", lambda **kw: str(output))
    select(app, monkeypatch)
    app.process.invoke()
    try:
        assert entered.wait(5)
        deadline = time.monotonic() + 3
        while app.status.get() != "Reading the source workbook…" and time.monotonic() < deadline:
            root.update()
            time.sleep(0.01)
        assert app.busy and app.state == "processing"
        assert app.progress.winfo_ismapped()
        assert app.status.get() == "Reading the source workbook…"
        assert str(app.choose["state"]) == str(app.process["state"]) == "disabled"
        assert app.process["text"] == "Processing…"
        (app.dark_mode if mode == "dark" else app.light_mode).invoke()
        root.update()
        app.reset()  # Cannot reset or re-select an input during a run.
        app.choose_file()
        assert app.selected == FIXTURE and app.busy and app.theme.get() == mode
        assert worker_ids == [worker_ids[0]] and worker_ids[0] != threading.get_ident()
    finally:
        release.set()
    run_until_done(root, app)
    root.update()
    assert app.state == "warning" and app.theme.get() == mode
    assert [c.get() for c in app.counts.values()] == ["3", "5", "3", "2"]
    assert app.output_name.get().endswith("organized.xlsx")
    assert app.issues_name.get().endswith("organized_issues.xlsx")
    assert app.paths.winfo_ismapped()
    assert not app.source_card.winfo_ismapped()
    for path in (output, tmp_path / "organized_issues.xlsx"):
        book = openpyxl.load_workbook(path)
        expected = (
            ["Issues"]
            if "issues" in path.stem
            else ["Events", "Equipment Requests", "Equipment Summary"]
        )
        assert book.sheetnames == expected
        book.close()
    assert hashlib.sha256(FIXTURE.read_bytes()).digest() == before
    snapshot = app.summary.get()
    app.dark_mode.invoke()
    app.light_mode.invoke()
    assert app.summary.get() == snapshot


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_clean_success_and_reset_are_session_only(ui, mode):
    root, app = ui
    (app.dark_mode if mode == "dark" else app.light_mode).invoke()
    app.complete(ProcessingResult(output_path=Path("output.xlsx"), event_count=1))
    root.update()
    assert app.state == "success"
    assert app.heading.get() == "Processing complete"
    assert app.style.lookup(app.status_heading["style"], "foreground") == PALETTES[mode]["success"]
    assert app.issues_name.get() == "No issues workbook needed."
    assert not app.issue_entry.winfo_ismapped()
    assert str(app.open_folder["state"]) == "normal"
    app.another.invoke()
    root.update()
    assert app.state == "idle" and app.selected is None and app.output is None
    assert app.summary.get() == "" and app.output_file.get() == app.issues_file.get() == ""
    assert app.theme.get() == mode
    assert app.source_card.winfo_ismapped() and not app.paths.winfo_ismapped()
    assert str(app.process["state"]) == str(app.open_folder["state"]) == "disabled"


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_error_state_uses_real_error_and_clears_stale_output(ui, monkeypatch, mode):
    root, app = ui
    (app.dark_mode if mode == "dark" else app.light_mode).invoke()
    app.complete(ProcessingResult(output_path=Path("old.xlsx"), event_count=3))
    errors = []
    monkeypatch.setattr(
        "ems_event_processor.ui.messagebox.showerror", lambda *args, **kw: errors.append(args)
    )
    app.complete(
        ProcessingResult(fatal_errors=("Close the destination workbook in Excel and try again.",))
    )
    root.update()
    assert app.state == "error" and "failed" in app.status.get()
    assert "Close the destination workbook" in app.detail.get()
    assert errors and app.output is None
    assert app.style.lookup(app.status_heading["style"], "foreground") == PALETTES[mode]["error"]
    assert not app.paths.winfo_ismapped() and str(app.open_folder["state"]) == "disabled"
    assert all(c.get() == "—" for c in app.counts.values())


def test_open_output_folder_keeps_platform_behavior_and_error_handling(ui, monkeypatch, tmp_path):
    import ems_event_processor.ui as ui_module

    root, app = ui
    app.output = tmp_path / "organized.xlsx"
    calls = []
    if ui_module.sys.platform == "win32":
        monkeypatch.setattr(ui_module.os, "startfile", lambda folder: calls.append(folder))
    else:
        monkeypatch.setattr(ui_module.subprocess, "Popen", lambda args: calls.append(args))
    app.open_output()
    assert str(tmp_path) in (calls[0] if isinstance(calls[0], list) else [calls[0]])

    def blocked(*args, **kwargs):
        raise OSError("folder shell unavailable")

    if ui_module.sys.platform == "win32":
        monkeypatch.setattr(ui_module.os, "startfile", blocked)
    else:
        monkeypatch.setattr(ui_module.subprocess, "Popen", blocked)
    errors = []
    monkeypatch.setattr(ui_module.messagebox, "showerror", lambda *args, **kw: errors.append(args))
    app.open_output()
    assert errors and str(tmp_path) in errors[0][1]


def relative_luminance(color):
    rgb = [int(color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return sum(c * factor for c, factor in zip(linear, (0.2126, 0.7152, 0.0722), strict=True))


@pytest.mark.parametrize("mode", ["light", "dark"])
def test_enabled_text_and_status_palette_contrast(mode):
    colors = PALETTES[mode]
    for foreground, background in [
        ("text", "background"),
        ("text", "surface"),
        ("muted", "surface"),
        ("muted", "field"),
        ("primary_text", "primary"),
        ("success", "surface"),
        ("warning", "surface"),
        ("error", "surface"),
    ]:
        a, b = sorted(
            (relative_luminance(colors[foreground]), relative_luminance(colors[background]))
        )
        assert (b + 0.05) / (a + 0.05) >= 4.5, (mode, foreground, background)


@pytest.mark.parametrize("scaling", [1.3333, 2.0])
@pytest.mark.parametrize("mode", ["light", "dark"])
def test_layout_remains_reachable_at_normal_and_large_scaling(ui_root, scaling, mode):
    root = ui_root
    previous = float(root.tk.call("tk", "scaling"))
    try:
        root.tk.call("tk", "scaling", scaling)
        app = Application(root)
        root.geometry("820x740")
        (app.dark_mode if mode == "dark" else app.light_mode).invoke()
        root.update()
        for widget in [app.title, app.light_mode, app.dark_mode, app.choose, app.process]:
            assert widget.winfo_rootx() >= root.winfo_rootx()
            assert (
                widget.winfo_rootx() + widget.winfo_width()
                <= root.winfo_rootx() + root.winfo_width()
            )
        app.complete(
            ProcessingResult(
                output_path=Path("organized.xlsx"),
                issues_path=Path("organized_issues.xlsx"),
                event_count=12345,
                equipment_request_count=54321,
                summary_row_count=1234,
                issue_count=9,
            )
        )
        root.update()
        # At larger scaling the cards use two columns; unused grid columns must
        # not reserve half the results area after switching from four columns.
        right_edge = max(card.winfo_x() + card.winfo_width() for card in app.metric_frames)
        assert right_edge >= app.metrics.winfo_width() - 8
        if app.content.winfo_height() > app.canvas.winfo_height():
            assert app.scroll.winfo_ismapped()
        app.canvas.yview_moveto(1)
        root.update()
        for widget in (app.open_folder, app.another):
            assert (
                widget.winfo_rootx() + widget.winfo_width()
                <= root.winfo_rootx() + root.winfo_width()
            )
            assert (
                widget.winfo_rooty() + widget.winfo_height()
                <= root.winfo_rooty() + root.winfo_height()
            )
    finally:
        root.tk.call("tk", "scaling", previous)
