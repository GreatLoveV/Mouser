"""Broader search: effect packets with different sizes, on every zone id.
Restores all zones to static blue at the end."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mouser.razer import NOSTORE, VARSTORE, BasiliskV3, RazerError  # noqa: E402

m = BasiliskV3.open()
C1, C2 = [0, 180, 255], [255, 59, 107]
cands = {
    "breathing single": [0x02, 0x01, 0x00, 0x01, *C1],
    "breathing dual": [0x02, 0x02, 0x00, 0x02, *C1, *C2],
    "breathing random": [0x02, 0x03, 0x00, 0x00],
    "reactive": [0x05, 0x00, 0x02, 0x01, *C1],
    "wave left": [0x04, 0x01, 0x28, 0x00],
    "wave right": [0x04, 0x02, 0x28, 0x00],
}
for led in (0x00, 0x01, 0x04, 0x0A):
    for store in (VARSTORE, NOSTORE):
        for name, args in cands.items():
            for size in sorted({len(args) + 2, 0x06, 0x09, 0x0C}):
                try:
                    m.transact(0x0F, 0x02, size, [store, led, *args])
                    print(f"OK   led={led:#04x} store={store} size={size:#04x} {name}")
                    break
                except RazerError:
                    pass
for led in (0x01, 0x04, 0x0A):
    m.effect_static((0, 180, 255), led)
print("restored all zones to static blue")
m.close()
