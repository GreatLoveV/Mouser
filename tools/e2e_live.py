"""End-to-end check that the app notices changes made *on the mouse*, as if you
pressed its DPI button, held the sensitivity clutch, or pressed scroll mode.

It changes the mouse from a separate HID handle (so the app didn't cause it),
then reads the app's event stream. Everything is restored at the end."""
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mouser.razer import BasiliskV3  # noqa: E402

s = json.load(open(os.path.join(os.environ["APPDATA"], "Mouser", "session.json")))
BASE = f"http://127.0.0.1:{s['port']}"


def call(path):
    req = urllib.request.Request(BASE + path, headers={"X-Mouser-Token": s["token"]})
    return json.load(urllib.request.urlopen(req))


def events_after(seq, wait=1.0):
    end = time.time() + wait
    out = []
    while time.time() < end:
        r = call(f"/api/live?since={seq}")
        out += r["events"]
        seq = r["seq"]
        time.sleep(0.1)
    return seq, out, r["state"]


st = call("/api/state")
seq = st["seq"]
call(f"/api/live?since={seq}")  # mark the window as open so the app watches closely
time.sleep(0.3)
m = BasiliskV3.open()
active, stages = m.get_dpi_stages()
results = []

# 1. "Press the DPI button": the mouse moves to the next stage by itself.
nxt = active % len(stages) + 1
m.set_dpi_stages(stages, nxt)
m.set_dpi(*stages[nxt - 1])
seq, ev, state = events_after(seq)
kinds = [(e["kind"], e.get("name") or e.get("cause")) for e in ev]
ok = ("hw_button", "dpi") in kinds and state["active_stage"] == nxt
results.append(("DPI button -> stage %d shown" % nxt, ok, kinds))

# 2. Another program changes the DPI: shown, and NOT mistaken for the clutch.
#    (The real clutch only announces itself in an input report, which a script
#    can't fake; press the real clutch to check that part.)
m.set_dpi(1200, 1200)
seq, ev1, state1 = events_after(seq, 0.6)
m.set_dpi(*stages[nxt - 1])
seq, ev2, state2 = events_after(seq, 0.6)
ok = state1["dpi"] == [1200, 1200] and not state1["clutch"] and state2["dpi"] == list(stages[nxt - 1])
results.append(("Outside DPI change shown, not taken for clutch", ok, [e["kind"] for e in ev1 + ev2]))

# 3. "Press scroll mode": free-spin flips.
fs = m.get_scroll()["free_spin"]
m.set_scroll("free_spin", not fs)
seq, ev, state = events_after(seq, 1.0)
ok = any(e["kind"] == "hw_button" and e.get("name") == "scroll_mode" for e in ev) and state["scroll"]["free_spin"] == (not fs)
results.append(("Scroll mode button", ok, [e["kind"] for e in ev]))
m.set_scroll("free_spin", fs)

# restore
m.set_dpi_stages(stages, active)
m.set_dpi(*stages[active - 1])
m.close()
seq, ev, state = events_after(seq, 1.0)
results.append(("Restored to stage %d" % active, state["active_stage"] == active and not state["scroll"]["free_spin"] == (not fs), []))

for name, ok, detail in results:
    print(("PASS " if ok else "FAIL ") + name, detail if not ok else "")
