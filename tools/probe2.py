"""Probe 2: verify polling/scroll writes round-trip, and try reading the current
lighting effect back from the mouse. Restores everything it changes."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mouser.razer import VARSTORE, BasiliskV3, RazerError  # noqa: E402

m = BasiliskV3.open()

orig = m.get_polling()
m.set_polling(500)
print("polling write 500 ->", m.get_polling())
m.set_polling(orig)
print("polling restored ->", m.get_polling())

sc = m.get_scroll()
print("scroll before", sc)
for key in ("smart_reel", "acceleration"):
    m.set_scroll(key, not sc[key])
    print(f"  {key} flipped ->", m.get_scroll()[key])
    m.set_scroll(key, sc[key])
print("scroll restored", m.get_scroll())

for led in (0x01, 0x04, 0x0A):
    for size in (0x0C, 0x09, 0x06):
        try:
            r = m.transact(0x0F, 0x82, size, [VARSTORE, led])
            print(f"effect read led {led:#04x} size {size:#04x}:", r.args[:12].hex(" "))
            break
        except RazerError as e:
            print(f"effect read led {led:#04x} size {size:#04x}: {e}")
t0 = time.perf_counter()
for _ in range(20):
    m.get_dpi()
    m.get_dpi_stages()
print(f"dpi+stages read: {(time.perf_counter() - t0) / 20 * 1000:.1f} ms per pair")
m.close()
