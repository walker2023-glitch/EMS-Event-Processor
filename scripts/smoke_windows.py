"""Verify the distributed executable opens its real Tk window on Windows."""

import ctypes
import subprocess
import time
from pathlib import Path


def main():
    executable = Path("dist/EMS Event Processor/EMS Event Processor.exe").resolve()
    process = subprocess.Popen([str(executable)])
    user32 = ctypes.windll.user32
    user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
    user32.FindWindowW.restype = ctypes.c_void_p
    user32.PostMessageW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.c_size_t,
        ctypes.c_ssize_t,
    ]
    window = None
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and process.poll() is None:
            window = user32.FindWindowW(None, "EMS Event Processor")
            if window:
                break
            time.sleep(0.1)
        if not window:
            raise RuntimeError("Packaged executable did not open its application window")
        user32.PostMessageW(window, 0x0010, 0, 0)  # WM_CLOSE: exercise normal Tk shutdown.
        if process.wait(timeout=15) != 0:
            raise RuntimeError("Packaged executable failed during shutdown")
        print("Packaged Windows application opened and closed successfully.")
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)


if __name__ == "__main__":
    main()
