"""Switch the mouse to DPI stage N directly (as the DPI button would), bypassing the app."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mouser.razer import BasiliskV3  # noqa: E402

m = BasiliskV3.open()
active, st = m.get_dpi_stages()
n = active if sys.argv[1] == "current" else int(sys.argv[1])  # "current" = re-apply the active stage's DPI
m.set_dpi_stages(st, n)
m.set_dpi(*st[n - 1])
m.close()
print(f"mouse now on stage {n} ({st[n - 1][0]} DPI)")
