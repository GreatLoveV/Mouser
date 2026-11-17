"""Find the argument layout this firmware accepts for breathing, wave and reactive
(on the logo zone), then put the logo back to static blue."""
import itertools
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mouser.razer import VARSTORE, BasiliskV3, RazerError  # noqa: E402

m = BasiliskV3.open()
LOGO = 0x04
C1, C2 = [0, 180, 255], [255, 59, 107]


def tryit(label, size, args):
    try:
        m.transact(0x0F, 0x02, size, [VARSTORE, LOGO, *args])
        back = m.transact(0x0F, 0x82, 0x0C, [VARSTORE, LOGO]).args[:12].hex(" ")
        print(f"OK   {label:38s} size={size:#04x} args={bytes(args).hex(' ')} -> {back}")
        return True
    except RazerError as e:
        return False


found = {}
for p3, p4 in itertools.product((0, 1, 2, 3), (0, 1, 2, 3, 0x28)):
    for name, size, args in (
        ("breathing single", 0x09, [0x02, p3, p4, 0x01, *C1]),
        ("breathing dual", 0x0C, [0x02, p3, p4, 0x02, *C1, *C2]),
        ("breathing random", 0x06, [0x02, p3, p4, 0x00]),
        ("reactive", 0x09, [0x05, p3, p4, 0x01, *C1]),
        ("wave", 0x06, [0x04, p3, p4, 0x00]),
    ):
        if name in found:
            continue
        if tryit(f"{name} p3={p3} p4={p4}", size, args):
            found[name] = (p3, p4)
print("accepted:", found or "none")
m.effect_static((0, 180, 255), LOGO)
print("logo restored to", m.get_effect(LOGO))
m.close()
