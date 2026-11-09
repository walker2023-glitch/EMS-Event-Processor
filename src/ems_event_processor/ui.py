"""One-screen Tkinter app. All Tk calls stay on the main thread."""

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .models import ProcessingResult
from .processor import process_workbook


class Application:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("EMS Event Processor")
        self.root.minsize(640, 440)
        self.file = tk.StringVar(value="No Excel file selected")
        self.status = tk.StringVar(value="Choose a local Excel workbook to begin.")
        self.summary = tk.StringVar()
        self.selected: Path | None = None
        self.output: Path | None = None
        self.busy = False
        self.messages: queue.Queue[str | ProcessingResult | Exception] = queue.Queue()
        frame = ttk.Frame(root, padding=24)
        frame.grid(sticky="nsew")
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        ttk.Label(frame, text="EMS Event Processor", font=("Segoe UI", 19)).grid(sticky="w")
        self.choose = ttk.Button(frame, text="Choose Excel File", command=self.choose_file)
        self.choose.grid(sticky="w", pady=(20, 8))
        display = ttk.Entry(frame, textvariable=self.file, state="readonly", width=75)
        display.grid(sticky="ew", pady=(0, 16))
        self.process = ttk.Button(
            frame, text="Process File", command=self.process_file, state="disabled"
        )
        self.process.grid(sticky="w")
        self.progress = ttk.Progressbar(frame, mode="indeterminate")
        self.progress.grid(sticky="ew", pady=(16, 8))
        ttk.Label(frame, textvariable=self.status, wraplength=590).grid(sticky="w")
        ttk.Label(frame, textvariable=self.summary, wraplength=590, justify="left").grid(
            sticky="w", pady=16
        )
        self.open_folder = ttk.Button(
            frame, text="Open Output Folder", command=self.open_output, state="disabled"
        )
        self.open_folder.grid(sticky="w")
        self.choose.focus_set()
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(75, self.poll)

    def choose_file(self) -> None:
        chosen = filedialog.askopenfilename(
            parent=self.root,
            title="Choose Excel File",
            filetypes=[("Excel workbooks", "*.xls *.xlsx"), ("All files", "*.*")],
        )
        if chosen:
            self.selected = Path(chosen)
            self.file.set(chosen)
            self.process.configure(state="normal")
            self.summary.set("")
            self.status.set("Ready. Click Process File to choose the output location.")

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
        self.summary.set("")
        self.output = None
        self.choose.configure(state="disabled")
        self.process.configure(state="disabled")
        self.open_folder.configure(state="disabled")
        self.progress.start(12)
        self.status.set("Starting processing…")
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
        self.choose.configure(state="normal")
        self.process.configure(state="normal")
        if isinstance(result, Exception) or not result.success:
            error = str(result) if isinstance(result, Exception) else "\n".join(result.fatal_errors)
            self.status.set("Processing failed. No successful output was reported.")
            self.summary.set(error)
            messagebox.showerror("Cannot process workbook", error, parent=self.root)
            return
        self.output = result.output_path
        self.open_folder.configure(state="normal")
        self.status.set("Processing complete. Review any issues before using the output.")
        self.summary.set(
            f"Events: {result.event_count:,}   "
            f"Equipment requests: {result.equipment_request_count:,}"
            f"   Summary rows: {result.summary_row_count:,}   Issues: {result.issue_count:,}\n"
            f"Output: {result.output_path}\n"
            f"Issues: {result.issues_path or 'None'}\n" + "\n".join(result.warnings)
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
