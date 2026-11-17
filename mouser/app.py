"""Entry point: one instance, background engine, tray icon, app window."""
from __future__ import annotations

import ctypes
import json
import os
import secrets
import shutil
import subprocess
import sys
import threading
import urllib.request
import webbrowser

from .config import APP_DIR
from .engine import Engine
from .server import make_server
from .tray import Tray

PORT = 47391
SESSION = os.path.join(APP_DIR, "session.json")
MUTEX_NAME = "Local\\MouserBasiliskV3"


def _edge() -> str | None:
    for p in (os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
              os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
              os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe")):
        if os.path.isfile(p):
            return p
    return shutil.which("msedge") or shutil.which("chrome")


def open_window(port: int, token: str) -> None:
    url = f"http://127.0.0.1:{port}/#t={token}"
    exe = _edge()
    if exe:
        profile = os.path.join(APP_DIR, "window")
        subprocess.Popen([exe, f"--app={url}", f"--user-data-dir={profile}", "--window-size=1180,800",
                          "--no-first-run", "--disable-features=Translate"], close_fds=True)
    else:
        webbrowser.open(url)


def _already_running() -> bool:
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = ctypes.c_void_p
    _already_running.handle = k32.CreateMutexW(None, False, MUTEX_NAME)  # keep alive
    return ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS


def main(argv: list[str]) -> int:
    no_window = "--background" in argv
    if _already_running():
        try:
            with open(SESSION, encoding="utf-8") as f:
                s = json.load(f)
            with urllib.request.urlopen(f"http://127.0.0.1:{s['port']}/api/ping", timeout=2):
                pass
            open_window(s["port"], s["token"])
            return 0
        except (OSError, ValueError, KeyError):
            print("Mouser is already running but not answering. Quit it from the tray and try again.")
            return 1

    token = secrets.token_urlsafe(32)
    engine = Engine()
    engine.start()

    port = PORT
    for candidate in range(PORT, PORT + 20):
        try:
            done = threading.Event()
            server = make_server(engine, token, candidate, lambda: done.set())
            port = candidate
            break
        except OSError:
            continue
    else:
        print("No free local port for Mouser.")
        return 1

    os.makedirs(APP_DIR, exist_ok=True)
    with open(SESSION, "w", encoding="utf-8") as f:
        json.dump({"port": port, "token": token}, f)

    threading.Thread(target=server.serve_forever, name="http", daemon=True).start()

    tray = Tray(
        on_open=lambda: open_window(port, token),
        on_toggle_pause=lambda: engine.set_paused(not engine.paused),
        is_paused=lambda: engine.paused,
        on_quit=lambda: done.set(),
    )
    threading.Thread(target=tray.run, name="tray", daemon=True).start()
    if not no_window:
        open_window(port, token)

    print(f"Mouser running on http://127.0.0.1:{port}  (quit from the tray icon or Ctrl+C)")
    try:
        while not done.wait(0.5):
            pass
    except KeyboardInterrupt:
        pass
    tray.close()
    server.shutdown()
    engine.stop()
    try:
        os.remove(SESSION)
    except OSError:
        pass
    return 0
