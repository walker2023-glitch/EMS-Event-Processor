"""Single-screen desktop UI. Processing stays in the unchanged background worker."""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

from .models import ProcessingResult
from .processor import process_workbook
from .ui_theme import apply_styles


class Application:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("EMS Event Processor")
        self.root.minsize(760, 560)
        self.root.geometry(f"820x{min(820, max(560, root.winfo_screenheight() - 100))}")
        self.file = tk.StringVar(value="No Excel file selected")
        self.filename = tk.StringVar(value="No file selected")
        self.status = tk.StringVar(value="Choose a local Excel workbook to begin.")
        self.summary = tk.StringVar()
        self.heading = tk.StringVar(value="Ready to process")
        self.detail = tk.StringVar(value="Your results will appear here after processing.")
        self.theme = tk.StringVar(value="light")
        self.counts = {
            name: tk.StringVar(value="—")
            for name in ("Events", "Equipment Requests", "Equipment Summary Rows", "Issues")
        }
        self.output_name = tk.StringVar()
        self.output_file = tk.StringVar()
        self.issues_name = tk.StringVar()
        self.issues_file = tk.StringVar()
        self.selected: Path | None = None
        self.output: Path | None = None
        self.busy = False
        self.state = "idle"
        self.messages: queue.Queue[str | ProcessingResult | Exception] = queue.Queue()
        self.style = ttk.Style(root)
        available = {name.casefold(): name for name in tkfont.families(root)}
        self.font_family = next(
            (
                available[name]
                for name in ("inter", "segoe ui", "helvetica", "arial")
                if name in available
            ),
            "Helvetica",
        )
        self._wrapping: list[tuple[ttk.Label, int]] = []
        self._build()
        self.set_theme()
        self.choose.focus_set()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(75, self.poll)

    def _label(
        self,
        parent: ttk.Frame,
        text: str = "",
        *,
        variable: tk.StringVar | None = None,
        style: str = "Card.TLabel",
        wrap: int = 100,
    ) -> ttk.Label:
        label = ttk.Label(parent, text=text, style=style, justify="left", wraplength=700)
        if variable is not None:
            label.configure(textvariable=variable)
        self._wrapping.append((label, wrap))
        return label

    def _build(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self.root, highlightthickness=0, borderwidth=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scroll = ttk.Scrollbar(self.root, orient="vertical", command=self.canvas.yview)
        self.scroll.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.content = ttk.Frame(self.canvas, padding=28)
        self.content.columnconfigure(0, weight=1)
        self.window = self.canvas.create_window(0, 0, window=self.content, anchor="nw")
        self.canvas.bind("<Configure>", self._resize)
        self.content.bind("<Configure>", self._content_size)
        self.root.bind("<MouseWheel>", self._wheel)
        self.root.bind("<Button-4>", lambda event: self.canvas.yview_scroll(-3, "units"))
        self.root.bind("<Button-5>", lambda event: self.canvas.yview_scroll(3, "units"))
        self.root.bind("<FocusIn>", self._focus_visible, add="+")

        header = ttk.Frame(self.content)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 20))
        header.columnconfigure(0, weight=1)
        self.title = self._label(header, "EMS Event Processor", style="Title.TLabel", wrap=340)
        self.title.grid(row=0, column=0, sticky="w")
        modes = ttk.Frame(header)
        self.modes = modes
        modes.grid(row=0, column=1, sticky="ne", padx=(12, 0))
        self.light_mode = ttk.Radiobutton(
            modes,
            text="Light Mode",
            value="light",
            variable=self.theme,
            command=self.set_theme,
            style="Theme.TRadiobutton",
            takefocus=True,
        )
        self.light_mode.grid(row=0, column=0)
        self.dark_mode = ttk.Radiobutton(
            modes,
            text="Dark Mode",
            value="dark",
            variable=self.theme,
            command=self.set_theme,
            style="Theme.TRadiobutton",
            takefocus=True,
        )
        self.dark_mode.grid(row=0, column=1)
        self._label(
            header,
            "Organize event and equipment information from an Excel report.",
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 5))
        self._label(
            header,
            "Select an Excel file, process it, and save the organized workbook.",
            style="Footnote.TLabel",
        ).grid(row=2, column=0, columnspan=2, sticky="w")

        self.source_card = ttk.Frame(self.content, style="Card.TFrame", padding=20)
        self.source_card.grid(row=1, column=0, sticky="ew", pady=(0, 20))
        self.source_card.columnconfigure(0, weight=1)
        self._label(self.source_card, "Input Excel File", style="CardTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            self.source_card, text="Supported formats: .xls and .xlsx", style="Muted.TLabel"
        ).grid(row=1, column=0, sticky="w", pady=(4, 14))
        self.selection_area = ttk.Frame(self.source_card, style="Field.TFrame", padding=20)
        self.selection_area.grid(row=2, column=0, sticky="ew")
        self.selection_area.columnconfigure(0, weight=1)
        self.file_icon = ttk.Label(self.selection_area, text="XLS", style="FileIcon.TLabel")
        self.filename_label = self._label(
            self.selection_area, variable=self.filename, style="File.TLabel", wrap=330
        )
        self.file_hint = tk.StringVar(
            value="Browse your computer for an exported EMS event schedule"
        )
        self.hint_label = self._label(
            self.selection_area, variable=self.file_hint, style="FileHint.TLabel", wrap=150
        )
        self.choose = ttk.Button(
            self.selection_area,
            text="Choose Excel File",
            command=self.choose_file,
            style="Primary.TButton",
            takefocus=True,
        )
        self.file_display = ttk.Entry(
            self.source_card, textvariable=self.file, state="readonly", style="Path.TEntry", width=1
        )
        self.file_display.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        self._selection_layout(False)

        self.results = ttk.Frame(self.content, style="Card.TFrame", padding=20)
        self.results.grid(row=2, column=0, sticky="ew")
        self.results.columnconfigure(0, weight=1)
        self.status_heading = self._label(
            self.results, variable=self.heading, style="Status.TLabel"
        )
        self.status_heading.grid(row=0, column=0, sticky="w")
        self._label(self.results, variable=self.status, style="Muted.TLabel").grid(
            row=1, column=0, sticky="w", pady=(6, 12)
        )
        self.progress = ttk.Progressbar(
            self.results, mode="determinate", value=0, style="EMS.Horizontal.TProgressbar"
        )
        self.progress.grid(row=2, column=0, sticky="ew", pady=(0, 14))
        self.metrics = ttk.Frame(self.results, style="Inner.TFrame")
        self.metrics.grid(row=3, column=0, sticky="ew", pady=(0, 14))
        self.metric_frames: list[ttk.Frame] = []
        for name, count in self.counts.items():
            metric = ttk.Frame(self.metrics, style="Metric.TFrame", padding=12)
            metric.columnconfigure(0, weight=1)
            metric.rowconfigure(0, weight=1)
            ttk.Label(metric, text=name, style="MetricCaption.TLabel", wraplength=135).grid(
                sticky="w"
            )
            ttk.Label(metric, textvariable=count, style="MetricCount.TLabel").grid(
                sticky="sw", pady=(6, 0)
            )
            self.metric_frames.append(metric)
        self.metrics.grid_remove()
        self.detail_label = self._label(self.results, variable=self.detail, style="Muted.TLabel")
        self.detail_label.grid(row=4, column=0, sticky="w", pady=(0, 10))
        self.detail_label.grid_remove()
        self.paths = ttk.Frame(self.results, style="Inner.TFrame")
        self.paths.grid(row=5, column=0, sticky="ew", pady=(2, 14))
        self.paths.columnconfigure(0, weight=1)
        self._label(self.paths, "Generated Output Files", style="CardTitle.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 12)
        )
        self._label(self.paths, variable=self.output_name, style="Card.TLabel").grid(
            row=1, column=0, sticky="w"
        )
        ttk.Entry(
            self.paths,
            textvariable=self.output_file,
            style="Path.TEntry",
            state="readonly",
            width=1,
        ).grid(row=2, column=0, sticky="ew", pady=(5, 12))
        self._label(self.paths, variable=self.issues_name, style="Card.TLabel").grid(
            row=3, column=0, sticky="w"
        )
        self.issue_entry = ttk.Entry(
            self.paths,
            textvariable=self.issues_file,
            style="Path.TEntry",
            state="readonly",
            width=1,
        )
        self.issue_entry.grid(row=4, column=0, sticky="ew", pady=(5, 0))
        self.paths.grid_remove()
        self.process_actions = ttk.Frame(self.results, style="Inner.TFrame")
        self.process_actions.grid(row=6, column=0, sticky="ew", pady=(4, 0))
        self.process_actions.columnconfigure(0, weight=1)
        self._label(
            self.process_actions,
            "The original file will not be changed.",
            style="Muted.TLabel",
            wrap=350,
        ).grid(row=0, column=0, sticky="w")
        self.process = ttk.Button(
            self.process_actions,
            text="Process File",
            command=self.process_file,
            state="disabled",
            style="Primary.TButton",
            takefocus=True,
        )
        self.process.grid(row=0, column=1, sticky="e", padx=(12, 0))
        self.result_actions = ttk.Frame(self.results, style="Inner.TFrame")
        self.result_actions.grid(row=7, column=0, sticky="ew", pady=(4, 0))
        self.result_actions.columnconfigure(0, weight=1)
        self.open_folder = ttk.Button(
            self.result_actions,
            text="Open Output Folder",
            command=self.open_output,
            state="disabled",
            style="Secondary.TButton",
        )
        self.open_folder.grid(row=0, column=0, sticky="e", padx=(0, 10))
        self.another = ttk.Button(
            self.result_actions,
            text="Process Another File",
            command=self.reset,
            state="disabled",
            style="Primary.TButton",
        )
        self.another.grid(row=0, column=1, sticky="e")
        self.result_actions.grid_remove()
        for key, button, underline in (
            ("c", self.choose, 0),
            ("p", self.process, 0),
            ("o", self.open_folder, 0),
            ("a", self.another, 8),
            ("l", self.light_mode, 0),
            ("d", self.dark_mode, 0),
        ):
            button.configure(underline=underline)
            self._bind_accelerator(key, button)
        self._label(
            self.content,
            "Local processing only. No account or internet connection required.",
            style="Footnote.TLabel",
        ).grid(row=3, column=0, sticky="w", pady=(18, 4))
        self._label(self.content, "EMS Event Processor MVP", style="Footnote.TLabel").grid(
            row=4, column=0, sticky="w"
        )

    def _bind_accelerator(self, key: str, button: ttk.Button | ttk.Radiobutton) -> None:
        def invoke(event: tk.Event[tk.Misc]) -> None:
            button.invoke()

        self.root.bind("<Alt-" + key + ">", invoke)

    def _selection_layout(self, selected: bool) -> None:
        if selected:
            self.file_icon.grid(row=0, column=0, columnspan=1, rowspan=2, sticky="w", padx=(0, 14))
            self.selection_area.columnconfigure(0, weight=0)
            self.selection_area.columnconfigure(1, weight=1)
            self.filename_label.grid(row=0, column=1, columnspan=1, sticky="w")
            self.hint_label.grid(row=1, column=1, columnspan=1, sticky="w", pady=(4, 0))
            self.choose.configure(text="Change File", style="Secondary.TButton")
            self.choose.grid(row=0, column=2, columnspan=1, rowspan=2, sticky="e", padx=(14, 0))
            self.file_display.grid()
        else:
            self.selection_area.columnconfigure(0, weight=1)
            self.selection_area.columnconfigure(1, weight=0)
            self.file_icon.grid(row=0, column=0, columnspan=3, rowspan=1, padx=0, pady=(0, 8))
            self.filename_label.grid(row=1, column=0, columnspan=3)
            self.hint_label.grid(row=2, column=0, columnspan=3, pady=(4, 14))
            self.choose.configure(text="Choose Excel File", style="Primary.TButton")
            self.choose.grid(row=3, column=0, columnspan=3, rowspan=1, padx=0)
            self.file_display.grid_remove()
        self.canvas.yview_moveto(0)

    def _focus_visible(self, event: tk.Event[tk.Misc]) -> None:
        """Keep keyboard-reached controls visible when scaled content needs scrolling."""
        widget = event.widget
        if not isinstance(widget, tk.Misc) or widget == self.root or not widget.winfo_ismapped():
            return
        top = widget.winfo_rooty() - self.content.winfo_rooty()
        height = self.content.winfo_height()
        if height <= self.canvas.winfo_height():
            return
        visible_top = self.canvas.yview()[0] * height
        visible_bottom = visible_top + self.canvas.winfo_height()
        if top < visible_top:
            self.canvas.yview_moveto(max(0, top - 16) / height)
        elif top + widget.winfo_height() > visible_bottom:
            self.canvas.yview_moveto(
                (top + widget.winfo_height() + 16 - self.canvas.winfo_height()) / height
            )

    def _resize(self, event: tk.Event[tk.Misc]) -> None:
        self.canvas.itemconfigure(self.window, width=event.width)
        for label, margin in self._wrapping:
            label.configure(wraplength=max(180, event.width - margin))
        self.title.configure(wraplength=max(180, event.width - self.modes.winfo_reqwidth() - 90))
        columns = 2 if event.width < 650 * float(self.root.tk.call("tk", "scaling")) / 1.33 else 4
        for i in range(4):
            self.metrics.columnconfigure(
                i, weight=1 if i < columns else 0, uniform="metric" if i < columns else ""
            )
            self.metric_frames[i].grid(
                row=i // columns, column=i % columns, sticky="nsew", padx=(0, 6), pady=3
            )

    def _content_size(self, event: tk.Event[tk.Misc]) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        if self.content.winfo_height() <= self.canvas.winfo_height():
            self.scroll.grid_remove()
        else:
            self.scroll.grid()

    def _wheel(self, event: tk.Event[tk.Misc]) -> None:
        if self.content.winfo_height() > self.canvas.winfo_height():
            direction = -1 if event.delta > 0 else 1
            self.canvas.yview_scroll(direction * max(1, abs(event.delta) // 120) * 3, "units")

    def set_theme(self) -> None:
        colors = apply_styles(self.style, self.theme.get(), self.font_family)
        self.root.configure(background=colors["background"])
        self.canvas.configure(background=colors["background"])
        self._status_style()

    def _status_style(self) -> None:
        name = {"success": "Success", "warning": "Warning", "error": "Error"}.get(
            self.state, "Status"
        )
        self.status_heading.configure(style=name + ".TLabel")

    @staticmethod
    def _valid_file(path: Path | None) -> bool:
        try:
            return path is not None and path.suffix.lower() in {".xls", ".xlsx"} and path.is_file()
        except OSError:
            return False

    def _clear_results(self) -> None:
        self.output = None
        self.summary.set("")
        self.paths.grid_remove()
        self.metrics.grid_remove()
        self.result_actions.grid_remove()
        self.detail_label.grid_remove()
        self.output_name.set("")
        self.output_file.set("")
        self.issues_name.set("")
        self.issues_file.set("")
        for count in self.counts.values():
            count.set("—")
        self.open_folder.configure(state="disabled")

    def reset(self) -> None:
        if self.busy:
            return
        self._clear_results()
        self.selected = None
        self.filename.set("No file selected")
        self.file.set("No Excel file selected")
        self.source_card.grid()
        self.process_actions.grid()
        self.progress.configure(mode="determinate", value=0)
        self.progress.grid()
        self.file_hint.set("Browse your computer for an exported EMS event schedule")
        self._selection_layout(False)
        self.state = "idle"
        self.heading.set("Ready to process")
        self.status.set("Choose a local Excel workbook to begin.")
        self.detail.set("Your results will appear here after processing.")
        self.process.configure(state="disabled")
        self.another.configure(state="disabled")
        self._status_style()
        self.canvas.yview_moveto(0)
        self.choose.focus_set()

    def choose_file(self) -> None:
        if self.busy:
            return
        chosen = filedialog.askopenfilename(
            parent=self.root,
            title="Choose Excel File",
            filetypes=[("Excel workbooks", "*.xls *.xlsx"), ("All files", "*.*")],
        )
        if chosen:
            self._clear_results()
            self.selected = Path(chosen)
            self.file.set(chosen)
            self.filename.set(self.selected.name)
            self._selection_layout(True)
            self.source_card.grid()
            self.process_actions.grid()
            self.progress.configure(mode="determinate", value=0)
            self.progress.grid()
            self.another.configure(state="normal")
            if self._valid_file(self.selected):
                self.file_hint.set("Ready · " + self.selected.suffix.lower() + " workbook")
                self.process.configure(state="normal")
                self.state = "selected"
                self.heading.set("Ready to process")
                self.status.set("Ready. Click Process File to choose the output location.")
                self.detail.set("An organized workbook will be saved to the location you choose.")
            else:
                self.file_hint.set("File unavailable or unsupported")
                self.process.configure(state="disabled")
                self.state = "error"
                self.heading.set("Choose a supported workbook")
                self.status.set("Select an existing .xls or .xlsx file on this computer.")
                self.detail.set("Choose Excel File to select another workbook.")
            self._status_style()

    def process_file(self) -> None:
        if self.busy or self.selected is None:
            return
        output = filedialog.asksaveasfilename(
            parent=self.root,
            title="Save Organized Workbook",
            defaultextension=".xlsx",
            initialfile=self.selected.stem + "_organized.xlsx",
            filetypes=[("Excel workbook", "*.xlsx")],
            confirmoverwrite=True,
        )
        if not output:
            return
        self.busy = True
        self._clear_results()
        self.state = "processing"
        self.heading.set("Processing your workbook")
        self.detail.set("Please keep the application open. You can switch themes while you wait.")
        self.choose.configure(state="disabled")
        self.process.configure(state="disabled", text="Processing…")
        self.another.configure(state="disabled")
        self.detail_label.grid()
        self.progress.configure(mode="indeterminate")
        self.progress.grid()
        self.progress.start(12)
        self.status.set("Starting processing…")
        self._status_style()
        threading.Thread(target=self.work, args=(self.selected, Path(output)), daemon=True).start()

    def work(self, source: Path, output: Path) -> None:
        try:
            result = process_workbook(source, output, self.messages.put)
            self.messages.put(result)
        except Exception:
            self.messages.put(
                RuntimeError("Processing failed unexpectedly. The source is unchanged.")
            )

    def poll(self) -> None:
        try:
            while True:
                item = self.messages.get_nowait()
                if isinstance(item, str):
                    self.status.set(item)
                else:
                    self.complete(item)
        except queue.Empty:
            self.root.after(75, self.poll)

    def complete(self, result: ProcessingResult | Exception) -> None:
        self.busy = False
        self.progress.stop()
        self.progress.grid_remove()
        self.choose.configure(state="normal")
        self.process.configure(
            state="normal" if self._valid_file(self.selected) else "disabled", text="Process File"
        )
        self.another.configure(state="normal")
        if isinstance(result, Exception) or not result.success:
            error = str(result) if isinstance(result, Exception) else "\n".join(result.fatal_errors)
            self._clear_results()
            self.source_card.grid()
            self.process_actions.grid()
            self.result_actions.grid()
            self.detail_label.grid()
            self.state = "error"
            self.heading.set("Processing failed")
            self.status.set("Processing failed. No successful output was reported.")
            self.summary.set(error)
            self.detail.set(error)
            self._status_style()
            messagebox.showerror("Cannot process workbook", error, parent=self.root)
            return
        self.source_card.grid_remove()
        self.process_actions.grid_remove()
        self.metrics.grid()
        self.paths.grid()
        self.result_actions.grid()
        self.detail_label.grid()
        self.canvas.yview_moveto(0)
        self.output = result.output_path
        self.open_folder.configure(state="normal")
        self.open_folder.focus_set()
        self.state = "warning" if result.issue_count or result.warnings else "success"
        self.heading.set(
            "Processing complete — review required"
            if self.state == "warning"
            else "Processing complete"
        )
        self.status.set("Processing complete. Review any issues before using the output.")
        for name, count in zip(
            self.counts,
            (
                result.event_count,
                result.equipment_request_count,
                result.summary_row_count,
                result.issue_count,
            ),
            strict=True,
        ):
            self.counts[name].set(f"{count:,}")
        self.detail.set("\n".join(result.warnings) or "Your organized workbook is ready.")
        assert result.output_path is not None
        self.output_name.set("Organized workbook: " + result.output_path.name)
        self.output_file.set(str(result.output_path))
        self.issues_name.set(
            "Issues workbook: " + result.issues_path.name
            if result.issues_path
            else "No issues workbook needed."
        )
        self.issues_file.set(str(result.issues_path or ""))
        if result.issues_path:
            self.issue_entry.grid()
        else:
            self.issue_entry.grid_remove()
        self.paths.grid()
        self._status_style()
        self.summary.set(
            f"Events: {result.event_count:,}   "
            f"Equipment requests: {result.equipment_request_count:,}"
            f"   Summary rows: {result.summary_row_count:,}   Issues: {result.issue_count:,}\n"
            f"Output: {result.output_path}\nIssues: {result.issues_path or 'None'}\n"
            + "\n".join(result.warnings)
        )

    def open_output(self) -> None:
        if self.output is None:
            return
        folder = str(self.output.parent)
        try:
            if sys.platform == "win32":
                os.startfile(folder)
            else:
                subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", folder])
        except OSError:
            messagebox.showerror(
                "Cannot open folder", f"Open this folder manually:\n{folder}", parent=self.root
            )

    def close(self) -> None:
        if self.busy:
            messagebox.showinfo(
                "Processing in progress",
                "Wait for processing to finish before closing.",
                parent=self.root,
            )
        else:
            self.root.destroy()


def main() -> None:
    root = tk.Tk()
    Application(root)
    root.mainloop()
