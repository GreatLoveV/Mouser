"""End-to-end check of the running app: bind Back -> cycle DPI, simulate a Back
press with SendInput, confirm the mouse's DPI changed, then restore everything."""
import ctypes
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mouser.winput import INPUT, INPUT_MOUSE, MOUSEINPUT, user32  # noqa: E402

s = json.load(open(os.path.join(os.environ["APPDATA"], "Mouser", "session.json")))
BASE = f"http://127.0.0.1:{s['port']}"


def call(path, body=None):
    req = urllib.request.Request(BASE + path, headers={"X-Mouser-Token": s["token"], "Content-Type": "application/json"},
                                 data=None if body is None else json.dumps(body).encode())
    return json.load(urllib.request.urlopen(req))


def press_back():
    for flag in (0x0080, 0x0100):  # XDOWN, XUP with XBUTTON1 (= Back)
        i = INPUT(type=INPUT_MOUSE)
        i.u.mi = MOUSEINPUT(0, 0, 1, flag, 0, 0)
        arr = (INPUT * 1)(i)
        user32.SendInput(1, arr, ctypes.sizeof(INPUT))
        time.sleep(0.03)


before = call("/api/state")
since = before["seq"]
orig_profiles = before["profiles"]
print("before:", before["dpi"], "stage", before["active_stage"], before["stages"])
p = json.loads(json.dumps(orig_profiles))
p[0]["bindings"]["back"] = {"type": "dpi", "mode": "cycle"}
call("/api/profiles", {"profiles": p})
press_back()
time.sleep(0.4)
live = call(f"/api/live?since={since}")
after = call("/api/state")
seen = [e["name"] for e in live["events"] if e["kind"] == "button" and e["down"]]
live["last_button"] = {"name": seen[-1] if seen else None}
print("last button seen:", live["last_button"]["name"])
print("after: ", after["dpi"], "stage", after["active_stage"])
# restore
call("/api/profiles", {"profiles": orig_profiles})
call("/api/stages", {"stages": before["stages"], "active": before["active_stage"]})
final = call("/api/state")
print("restored:", final["dpi"], "stage", final["active_stage"], "bindings", final["profiles"][0]["bindings"])
ok = live["last_button"]["name"] == "back" and after["active_stage"] != before["active_stage"]
print("PASS" if ok else "FAIL")
