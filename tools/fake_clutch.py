"""Imitate holding the sensitivity clutch: drop DPI without changing stage, then restore."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mouser.razer import BasiliskV3  # noqa: E402

hold = float(sys.argv[1]) if len(sys.argv) > 1 else 3
m = BasiliskV3.open()
before = m.get_dpi()
m.set_dpi(400, 400)
time.sleep(hold)
m.set_dpi(*before)
m.close()
print("clutch released, back to", before)
