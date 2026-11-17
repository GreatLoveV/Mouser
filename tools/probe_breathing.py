"""Try each breathing variant on the logo and read back what the mouse stored."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mouser.razer import VARSTORE, BasiliskV3, RazerError  # noqa: E402

m = BasiliskV3.open()
LOGO = 0x04
before = m.get_effect(LOGO)
for label, cols in (("single", [(0, 180, 255)]), ("dual", [(0, 180, 255), (255, 59, 107)]), ("random", [])):
    try:
        m.effect_breathing(cols, LOGO)
        time.sleep(0.2)
        raw = m.transact(0x0F, 0x82, 0x0C, [VARSTORE, LOGO]).args[:12].hex(" ")
        print(f"{label:7s} write OK  -> read {raw}")
    except RazerError as e:
        print(f"{label:7s} write FAILED: {e}")
m.effect_static((0, 180, 255), LOGO)
print("restored:", m.get_effect(LOGO), "(was", before, ")")
m.close()
