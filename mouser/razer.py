"""Razer HID control protocol for the Basilisk V3 (USB 1532:0099).

Wire format (90-byte feature report, sent with report ID 0), as documented
by the OpenRazer project:

    0 status | 1 transaction id | 2-3 remaining packets | 4 protocol type
    5 data size | 6 command class | 7 command id | 8..87 arguments (80)
    88 CRC (XOR of bytes 2..87) | 89 reserved
"""
from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass

from .hid_win import HidDevice, enumerate_hid

RAZER_VID = 0x1532
BASILISK_V3_PID = 0x0099
TRANSACTION_ID = 0x1F
REPORT_LEN = 90

NOSTORE = 0x00
VARSTORE = 0x01

STATUS = {0x00: "new", 0x01: "busy", 0x02: "ok", 0x03: "failed", 0x04: "timeout", 0x05: "not supported"}

# LED ids (OpenRazer naming)
LED_ALL = 0x00
LED_SCROLL = 0x01
LED_LOGO = 0x04

POLLING = {1000: 0x01, 500: 0x02, 125: 0x08}
POLLING_REV = {v: k for k, v in POLLING.items()}

MATRIX_COLS = 11
MAX_DPI = 26000
MIN_DPI = 100


class RazerError(RuntimeError):
    """The mouse answered, but not the way we wanted (busy, refused, crossed replies)."""


class DeviceGone(RazerError):
    """Windows couldn't reach the mouse at all: it was unplugged."""


def build_report(cmd_class: int, cmd_id: int, size: int, args: bytes | list[int] = b"") -> bytes:
    r = bytearray(REPORT_LEN)
    r[1] = TRANSACTION_ID
    r[5] = size
    r[6] = cmd_class
    r[7] = cmd_id
    args = bytes(args)
    if len(args) > 80:
        raise ValueError("too many arguments")
    r[8:8 + len(args)] = args
    crc = 0
    for b in r[2:88]:
        crc ^= b
    r[88] = crc
    return bytes(r)


@dataclass
class Response:
    status: int
    cmd_class: int
    cmd_id: int
    size: int
    args: bytes

    @property
    def ok(self) -> bool:
        return self.status == 0x02


class BasiliskV3:
    """Talks to the mouse's control collection. Thread-safe."""

    def __init__(self, dev: HidDevice):
        self.dev = dev
        self.lock = threading.Lock()

    # ---------- discovery ----------
    @classmethod
    def open(cls) -> "BasiliskV3":
        candidates = [i for i in enumerate_hid(RAZER_VID, BASILISK_V3_PID) if i.feature_len >= REPORT_LEN + 1]
        # The control collection is usually on interface 0; try it first.
        candidates.sort(key=lambda i: ("mi_00" not in i.path.lower(), i.path))
        errors = []
        for c in candidates:
            try:
                dev = HidDevice(c.path)
            except OSError as e:
                errors.append(str(e))
                continue
            m = cls(dev)
            try:
                m.firmware()
                return m
            except RazerError as e:
                errors.append(f"{c.path}: {e}")
                dev.close()
        if not candidates:
            raise RazerError("Basilisk V3 not found. Is it plugged in by USB?")
        raise RazerError("Basilisk V3 found but it did not answer: " + "; ".join(errors))

    def close(self) -> None:
        self.dev.close()

    # ---------- transport ----------
    def transact(self, cmd_class: int, cmd_id: int, size: int, args=b"", expect_reply=True) -> Response:
        pkt = build_report(cmd_class, cmd_id, size, args)
        with self.lock:
            last = None
            # Other programs (Razer's own service, for one) may talk to the mouse
            # at the same time, so a crossed or refused reply gets a few retries.
            for attempt in range(8):
                if attempt:
                    # random back-off so two programs polling the mouse stop colliding
                    time.sleep(random.uniform(0.005, 0.03) * attempt)
                if not self.dev.set_feature(b"\x00" + pkt):
                    raise DeviceGone("write to mouse failed (unplugged?)")
                for _ in range(10):
                    time.sleep(0.004)
                    raw = self.dev.get_feature(0, REPORT_LEN + 1)
                    if raw is None:
                        raise DeviceGone("read from mouse failed (unplugged?)")
                    r = raw[1:]
                    last = Response(r[0], r[6], r[7], r[5], bytes(r[8:88]))
                    if last.status != 0x01:  # not busy
                        break
                if last and last.status == 0x02:
                    if (last.cmd_class, last.cmd_id) != (cmd_class, cmd_id):
                        continue  # stale reply from another command, retry
                    return last
                if last and last.status == 0x05:
                    break  # "not supported" won't change on a retry
        st = STATUS.get(last.status, hex(last.status)) if last else "no reply"
        raise RazerError(f"command {cmd_class:02x}:{cmd_id:02x} -> {st}")

    # ---------- info ----------
    def firmware(self) -> str:
        r = self.transact(0x00, 0x81, 0x02)
        return f"v{r.args[0]}.{r.args[1]:02d}"

    def serial(self) -> str:
        r = self.transact(0x00, 0x82, 0x16)
        return r.args[:22].split(b"\x00")[0].decode("ascii", "replace").strip()

    # ---------- polling ----------
    def get_polling(self) -> int:
        r = self.transact(0x00, 0x85, 0x01)
        return POLLING_REV.get(r.args[0], 0)

    def set_polling(self, hz: int) -> None:
        if hz not in POLLING:
            raise ValueError("polling rate must be 125, 500 or 1000")
        self.transact(0x00, 0x05, 0x01, [POLLING[hz]])

    # ---------- DPI ----------
    def get_dpi(self) -> tuple[int, int]:
        r = self.transact(0x04, 0x85, 0x07, [NOSTORE])
        a = r.args
        return (a[1] << 8) | a[2], (a[3] << 8) | a[4]

    def set_dpi(self, x: int, y: int | None = None) -> None:
        y = x if y is None else y
        x, y = _clamp_dpi(x), _clamp_dpi(y)
        self.transact(0x04, 0x05, 0x07, [NOSTORE, x >> 8, x & 0xFF, y >> 8, y & 0xFF, 0, 0])

    def get_dpi_stages(self) -> tuple[int, list[tuple[int, int]]]:
        r = self.transact(0x04, 0x86, 0x26, [VARSTORE])
        a = r.args
        active, count = a[1], a[2]
        stages = []
        for i in range(min(count, 5)):
            o = 3 + i * 7
            stages.append(((a[o + 1] << 8) | a[o + 2], (a[o + 3] << 8) | a[o + 4]))
        return active, stages

    def set_dpi_stages(self, stages: list[tuple[int, int]], active: int) -> None:
        if not 1 <= len(stages) <= 5:
            raise ValueError("1 to 5 DPI stages")
        active = max(1, min(active, len(stages)))
        args = [VARSTORE, active, len(stages)]
        for i, (x, y) in enumerate(stages, start=1):
            x, y = _clamp_dpi(x), _clamp_dpi(y)
            args += [i, x >> 8, x & 0xFF, y >> 8, y & 0xFF, 0, 0]
        self.transact(0x04, 0x06, 0x26, args)

    # ---------- lighting ----------
    def get_brightness(self, led: int = LED_ALL) -> int:
        r = self.transact(0x0F, 0x84, 0x03, [VARSTORE, led, 0])
        return r.args[2]

    def set_brightness(self, value: int, led: int = LED_ALL) -> None:
        self.transact(0x0F, 0x04, 0x03, [VARSTORE, led, max(0, min(255, value))])

    def effect_none(self, led: int = LED_ALL) -> None:
        self.transact(0x0F, 0x02, 0x06, [VARSTORE, led, 0x00, 0, 0, 0])

    def effect_static(self, rgb: tuple[int, int, int], led: int = LED_ALL) -> None:
        self.transact(0x0F, 0x02, 0x09, [VARSTORE, led, 0x01, 0, 0, 0x01, *rgb])

    def effect_breathing(self, colors: list[tuple[int, int, int]], led: int = LED_ALL) -> None:
        if not colors:
            self.transact(0x0F, 0x02, 0x06, [VARSTORE, led, 0x02, 0, 0, 0])
        elif len(colors) == 1:
            self.transact(0x0F, 0x02, 0x09, [VARSTORE, led, 0x02, 0x01, 0, 0x01, *colors[0]])
        else:
            self.transact(0x0F, 0x02, 0x0C, [VARSTORE, led, 0x02, 0x02, 0, 0x02, *colors[0], *colors[1]])

    def effect_spectrum(self, led: int = LED_ALL) -> None:
        self.transact(0x0F, 0x02, 0x06, [VARSTORE, led, 0x03, 0, 0, 0])

    def effect_wave(self, direction: int = 1, speed: int = 0x28, led: int = LED_ALL) -> None:
        self.transact(0x0F, 0x02, 0x06, [VARSTORE, led, 0x04, 1 if direction == 1 else 2, max(1, min(255, speed)), 0])

    def effect_reactive(self, rgb: tuple[int, int, int], speed: int = 2, led: int = LED_ALL) -> None:
        self.transact(0x0F, 0x02, 0x09, [VARSTORE, led, 0x05, 0, max(1, min(4, speed)), 0x01, *rgb])

    def get_effect(self, led: int) -> dict:
        """Read the effect stored for one LED zone (verified on firmware v1.00)."""
        a = self.transact(0x0F, 0x82, 0x0C, [VARSTORE, led]).args
        names = {0x00: "off", 0x01: "static", 0x02: "breathing", 0x03: "spectrum", 0x04: "wave", 0x05: "reactive"}
        effect = names.get(a[2], "static")
        count = a[5]
        colors = []
        for i in range(min(count, 2)):
            r, g, b = a[6 + i * 3: 9 + i * 3]
            colors.append(f"#{r:02x}{g:02x}{b:02x}")
        if effect == "wave":
            speed = max(1, min(4, 5 - round(a[4] / 0x14))) if a[4] else 2
        elif effect == "reactive":
            speed = max(1, min(4, a[4] or 2))
        else:
            speed = 2
        return {"effect": effect, "colors": colors, "speed": speed}

    def custom_frame(self, colors: list[tuple[int, int, int]]) -> None:
        """Set every LED individually (not saved on the mouse)."""
        colors = (colors + [(0, 0, 0)] * MATRIX_COLS)[:MATRIX_COLS]
        flat = [c for rgb in colors for c in rgb]
        self.transact(0x0F, 0x03, 5 + len(flat), [0, 0, 0, 0, MATRIX_COLS - 1, *flat])
        self.transact(0x0F, 0x02, 0x0C, [NOSTORE, LED_ALL, 0x08, 0, 0, 0])

    # ---------- scroll wheel ----------
    def get_scroll(self) -> dict:
        out = {}
        for key, cid in (("free_spin", 0x94), ("acceleration", 0x96), ("smart_reel", 0x97)):
            try:
                r = self.transact(0x02, cid, 0x02, [VARSTORE])
                out[key] = bool(r.args[1])
            except RazerError:
                out[key] = None
        return out

    def set_scroll(self, key: str, on: bool) -> None:
        cid = {"free_spin": 0x14, "acceleration": 0x16, "smart_reel": 0x17}[key]
        self.transact(0x02, cid, 0x02, [VARSTORE, 1 if on else 0])


def _clamp_dpi(v: int) -> int:
    v = int(round(v / 50.0) * 50)
    return max(MIN_DPI, min(MAX_DPI, v))
