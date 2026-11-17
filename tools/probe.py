"""Read-only probe: lists Basilisk V3 HID interfaces and reads current settings."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mouser.hid_win import enumerate_hid  # noqa: E402
from mouser.razer import BASILISK_V3_PID, RAZER_VID, BasiliskV3, RazerError  # noqa: E402

for i in enumerate_hid(RAZER_VID, BASILISK_V3_PID):
    print(f"page={i.usage_page:04x} usage={i.usage:04x} feat={i.feature_len:3d} {i.path}")

m = BasiliskV3.open()
print("control path:", m.dev.path)
for name in ("firmware", "serial", "get_polling", "get_dpi", "get_dpi_stages", "get_brightness", "get_scroll"):
    try:
        print(f"{name}: {getattr(m, name)()}")
    except RazerError as e:
        print(f"{name}: ERROR {e}")
for led, label in ((0x01, "scroll"), (0x04, "logo"), (0x0A, "underglow?")):
    try:
        print(f"brightness {label}: {m.get_brightness(led)}")
    except RazerError as e:
        print(f"brightness {label}: ERROR {e}")
m.close()
