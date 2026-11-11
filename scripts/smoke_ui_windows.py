"""Drive the packaged UI with real Windows input/dialogs; capture review images.

Uses Windows APIs and built-in .NET drawing only. Run on an interactive Windows
session after PyInstaller builds the executable. All data is invented fixtures.
"""

import base64
import ctypes
import hashlib
import subprocess
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

import openpyxl

USER32 = ctypes.windll.user32
USER32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
USER32.FindWindowW.restype = wintypes.HWND
USER32.SetForegroundWindow.argtypes = [wintypes.HWND]
USER32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
USER32.IsWindowVisible.argtypes = [wintypes.HWND]
USER32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]


class KeyboardInput(ctypes.Structure):
    _fields_ = [
        ("vk", wintypes.WORD),
        ("scan", wintypes.WORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("extra", ctypes.c_size_t),
    ]


class MouseInput(ctypes.Structure):
    _fields_ = [
        ("x", wintypes.LONG),
        ("y", wintypes.LONG),
        ("data", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("extra", ctypes.c_size_t),
    ]


class InputData(ctypes.Union):
    _fields_ = [("keyboard", KeyboardInput), ("mouse", MouseInput)]


class Input(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("data", InputData)]


USER32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(Input), ctypes.c_int]
USER32.SendInput.restype = wintypes.UINT


def wait_for(test, description, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = test()
        if value:
            return value
        time.sleep(0.1)
    raise RuntimeError("Timed out waiting for " + description)


def window(title):
    return USER32.FindWindowW(None, title)


def send(vk=0, scan=0, flags=0):
    item = Input(type=1, data=InputData(keyboard=KeyboardInput(vk, scan, flags, 0, 0)))
    if USER32.SendInput(1, ctypes.byref(item), ctypes.sizeof(item)) != 1:
        raise RuntimeError("Windows did not accept keyboard input")


def chord(modifier, key):
    send(modifier)
    send(key)
    send(key, flags=2)
    send(modifier, flags=2)
    time.sleep(0.15)


def shortcut(hwnd, letter):
    USER32.SetForegroundWindow(hwnd)
    time.sleep(0.15)
    chord(0x12, ord(letter.upper()))  # Alt + application mnemonic.


def enter_path(dialog, path):
    USER32.SetForegroundWindow(dialog)
    chord(0x12, ord("N"))  # Native common dialog: File name.
    chord(0x11, ord("A"))
    for char in str(path):
        send(scan=ord(char), flags=4)  # Unicode text, not virtual-key layout translation.
        send(scan=ord(char), flags=6)
    send(0x0D)
    send(0x0D, flags=2)
    wait_for(lambda: not USER32.IsWindowVisible(dialog), "file dialog to close")


def screenshot(hwnd, name, folder):
    USER32.SetForegroundWindow(hwnd)
    time.sleep(0.3)
    rect = wintypes.RECT()
    if not USER32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise RuntimeError("Cannot locate the application window")
    path = (folder / (name + ".png")).resolve()
    script = f"""
Add-Type -AssemblyName System.Drawing
$bitmap = [System.Drawing.Bitmap]::new({rect.right - rect.left}, {rect.bottom - rect.top})
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.CopyFromScreen({rect.left}, {rect.top}, 0, 0, $bitmap.Size)
$bitmap.Save('{str(path).replace("'", "''")}', [System.Drawing.Imaging.ImageFormat]::Png)
$graphics.Dispose()
$bitmap.Dispose()
"""
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    subprocess.run(
        ["powershell", "-NoProfile", "-EncodedCommand", encoded], check=True, capture_output=True
    )


def choose(hwnd, source):
    shortcut(hwnd, "c")
    dialog = wait_for(lambda: window("Choose Excel File"), "input dialog")
    enter_path(dialog, source)


def process(hwnd, output):
    shortcut(hwnd, "p")
    dialog = wait_for(lambda: window("Save Organized Workbook"), "output dialog")
    enter_path(dialog, output)


def main():
    folder = Path("work/ui-windows")
    folder.mkdir(parents=True, exist_ok=True)
    executable = Path("dist/EMS Event Processor/EMS Event Processor.exe").resolve()
    process_app = subprocess.Popen([str(executable)])
    try:
        hwnd = wait_for(lambda: window("EMS Event Processor"), "packaged app window")
        screenshot(hwnd, "01-light-initial", folder)
        shortcut(hwnd, "d")
        screenshot(hwnd, "02-dark-initial", folder)
        with tempfile.TemporaryDirectory(prefix="ems-ui-") as temporary:
            destination = Path(temporary)
            for extension in ("xlsx", "xls"):
                source = Path(f"tests/fixtures/sanitized_setup.{extension}").resolve()
                original = hashlib.sha256(source.read_bytes()).digest()
                choose(hwnd, source)
                screenshot(hwnd, f"03-dark-selected-{extension}", folder)
                output = destination / f"{extension}_organized.xlsx"
                process(hwnd, output)
                issues = output.with_name(output.stem + "_issues.xlsx")
                wait_for(
                    lambda out=output, review=issues: out.exists() and review.exists(),
                    "organized and issues workbooks",
                )
                time.sleep(0.5)  # Allow the main-thread completion queue to render.
                screenshot(hwnd, f"04-dark-complete-{extension}", folder)
                for path, expected in [
                    (output, ["Events", "Equipment Requests", "Equipment Summary"]),
                    (issues, ["Issues"]),
                ]:
                    book = openpyxl.load_workbook(path)
                    assert book.sheetnames == expected
                    assert book.worksheets[0].max_row == (4 if path == output else 3)
                    book.close()
                assert hashlib.sha256(source.read_bytes()).digest() == original
                shortcut(hwnd, "o")  # Exercise the packaged folder-opening action.
                time.sleep(0.5)
                shortcut(hwnd, "a")
            shortcut(hwnd, "l")
            corrupt = destination / "unreadable.xlsx"
            corrupt.write_text("invented unreadable workbook")
            choose(hwnd, corrupt)
            invalid_output = destination / "must_not_exist.xlsx"
            process(hwnd, invalid_output)
            error = wait_for(
                lambda: window("Cannot process workbook"), "plain-language error dialog"
            )
            screenshot(error, "05-native-error", folder)
            USER32.PostMessageW(error, 0x0010, 0, 0)
            wait_for(lambda: not USER32.IsWindowVisible(error), "error dialog to close")
            screenshot(hwnd, "06-light-error", folder)
            assert not invalid_output.exists()
        USER32.PostMessageW(hwnd, 0x0010, 0, 0)
        assert process_app.wait(timeout=15) == 0
        print(
            "Packaged UI passed: both themes, native dialogs, both Excel formats, completion, "
            "folder action, reset, error handling and source preservation."
        )
    finally:
        if process_app.poll() is None:
            process_app.terminate()
            process_app.wait(timeout=10)


if __name__ == "__main__":
    main()
