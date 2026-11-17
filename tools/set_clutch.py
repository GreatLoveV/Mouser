"""Bind Back to a 400 DPI sensitivity clutch in the Everywhere profile, then
simulate holding and releasing Back and report the mouse's DPI at each step."""
import ctypes
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mouser.winput import INPUT, INPUT_MOUSE, MOUSEINPUT, user32  # noqa: E402

CLUTCH_DPI = int(sys.argv[1]) if len(sys.argv) > 1 else 400
s = json.load(open(os.path.join(os.environ["APPDATA"], "Mouser", "session.json")))
BASE = f"http://127.0.0.1:{s['port']}"


def call(path, body=None):
    req = urllib.request.Request(BASE + path, headers={"X-Mouser-Token": s["token"], "Content-Type": "application/json"},
                                 data=None if body is None else json.dumps(body).encode())
    return json.load(urllib.request.urlopen(req))


def back(flag):  # 0x0080 = X down, 0x0100 = X up; data 1 = XBUTTON1 (Back)
    i = INPUT(type=INPUT_MOUSE)
    i.u.mi = MOUSEINPUT(0, 0, 1, flag, 0, 0)
    user32.SendInput(1, (INPUT * 1)(i), ctypes.sizeof(INPUT))


st = call("/api/state")
profiles = st["profiles"]
profiles[0]["bindings"]["back"] = {"type": "clutch", "dpi": CLUTCH_DPI}
call("/api/profiles", {"profiles": profiles})
print("bound: back ->", call("/api/state")["profiles"][0]["bindings"]["back"])

print("before:", call("/api/live")["dpi"])
back(0x0080)
time.sleep(0.4)
held = call("/api/live")["dpi"]
print("holding back:", held)
back(0x0100)
time.sleep(0.4)
released = call("/api/live")["dpi"]
print("released:", released)
print("PASS" if held == [CLUTCH_DPI, CLUTCH_DPI] and released == st["dpi"] else "FAIL")
