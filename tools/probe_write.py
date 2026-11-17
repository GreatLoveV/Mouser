"""Write probe: tries lighting commands per LED id and reports which ones the mouse accepts."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mouser.razer import BasiliskV3, RazerError  # noqa: E402

m = BasiliskV3.open()


def t(label, fn):
    try:
        fn()
        print(f"OK    {label}")
        return True
    except RazerError as e:
        print(f"FAIL  {label}: {e}")
        return False


leds = {0x00: "all", 0x01: "scroll", 0x04: "logo", 0x05: "backlight", 0x0A: "underglow?"}
for led, name in leds.items():
    t(f"static green on {name} ({led:#04x})", lambda: m.effect_static((0, 255, 0), led))
time.sleep(1.5)
t("custom frame rainbow", lambda: m.custom_frame([(255 * (i % 3 == 0), 255 * (i % 3 == 1), 255 * (i % 3 == 2)) for i in range(11)]))
time.sleep(1.5)
for led in (0x01, 0x04, 0x0A):
    t(f"spectrum on {led:#04x}", lambda: m.effect_spectrum(led))
t("dpi set 800 (unchanged)", lambda: m.set_dpi(800))
print("dpi now", m.get_dpi())
m.close()
