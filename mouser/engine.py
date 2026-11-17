"""Ties the mouse, the button hook and the profiles together.

The mouse is the source of truth. A monitor thread reads it continuously
while the window is open (about 10 times a second) and turns every change it
sees into an event: the DPI button, the sensitivity clutch, the scroll-mode
button, the profile button underneath. Button presses come from the mouse
hook. The window replays these events, so the drawing moves with the mouse.
"""
from __future__ import annotations

import collections
import itertools
import queue
import threading
import time

from . import winput
from .config import MEDIA, ZONES, Config, validate_lighting, validate_profiles
from .razer import BasiliskV3, DeviceGone, RazerError

CLICK_ONLY = {"tilt_left", "tilt_right"}  # these send no release event
LED_ZONES = {"scroll": 0x01, "logo": 0x04, "underglow": 0x0A}
UI_ACTIVE_FOR = 3.0      # seconds after the last window poll that we keep watching closely
FAST_TICK = 0.08          # DPI / stage reads while the window is open
SLOW_TICK = 1.0           # while the window is closed (just keeps the connection fresh)
OWN_CHANGE_GRACE = 0.6    # DPI changes we caused ourselves are not reported as button presses


def hex_rgb(h: str) -> tuple[int, int, int]:
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


class Engine:
    def __init__(self):
        self.config = Config()
        self.mouse: BasiliskV3 | None = None
        self.mouse_lock = threading.RLock()
        self.dev: dict = {"connected": False}
        self.error = ""
        self.foreground = ""
        self.active_profile = "default"
        self.paused = False
        self.events: collections.deque = collections.deque(maxlen=600)
        self._seq = itertools.count(1)
        self.last_seq = 0
        self._ui_seen = 0.0
        self._own_dpi_at = 0.0
        self._clutch_hw = False
        self._held: dict[str, dict] = {}
        self._clutch_restore: int | None = None
        self._jobs: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._next_connect = 0.0
        self._readers: dict = {}
        self._own_dpi_value: list | None = None
        self._clutch_override = False
        self._bindings: dict = {}
        self._refresh_bindings()
        self.hook = winput.MouseHook(self._on_button)

    # ---------- lifecycle ----------
    def start(self):
        threading.Thread(target=self._worker, name="actions", daemon=True).start()
        threading.Thread(target=self._watch_apps, name="apps", daemon=True).start()
        threading.Thread(target=self._monitor, name="monitor", daemon=True).start()
        self.hook.start()

    def stop(self):
        self._stop.set()
        self._wake.set()
        self.hook.stop()
        self._jobs.put(None)
        with self.mouse_lock:
            if self.mouse:
                self.mouse.close()

    # ---------- events ----------
    def emit(self, kind: str, **data):
        seq = next(self._seq)
        self.events.append({"seq": seq, "t": time.time(), "kind": kind, **data})
        self.last_seq = seq

    def live(self, since: int) -> dict:
        self._ui_seen = time.time()
        self._wake.set()
        evs = [e for e in list(self.events) if e["seq"] > since]
        gap = bool(self.events) and since and self.events[0]["seq"] > since + 1
        return {"seq": self.last_seq, "reset": gap, "events": evs, "state": self.snapshot()}

    # ---------- device access ----------
    def _connect(self) -> BasiliskV3 | None:
        with self.mouse_lock:
            if self.mouse:
                return self.mouse
            if time.time() < self._next_connect:
                return None
            self._next_connect = time.time() + 1.0  # don't hammer HID enumeration
            try:
                self.mouse = BasiliskV3.open()
                self.error = ""
                self._read_all(self.mouse)
                self._start_reports()
                self.emit("connection", connected=True)
            except (RazerError, OSError) as e:
                self.mouse = None
                self.error = str(e)
            return self.mouse

    def _drop(self, err: Exception):
        with self.mouse_lock:
            if self.mouse:
                self.mouse.close()
            self.mouse = None
            self.error = str(err)
            if self.dev.get("connected"):
                self.dev = {"connected": False}
                self.emit("connection", connected=False)

    def device(self, fn):
        """Run fn(mouse); reconnect once on failure. Raises RazerError if unavailable."""
        with self.mouse_lock:
            m = self._connect()
            if not m:
                self._next_connect = 0.0
                m = self._connect()
            if not m:
                raise RazerError(self.error or "mouse not connected")
            try:
                return fn(m)
            except (DeviceGone, OSError) as e:
                self._drop(e)  # unplugged (maybe replugged): reopen and try once more
            except RazerError:
                return fn(m)  # a crossed or refused reply: one more try, same connection
            self._next_connect = 0.0
            m = self._connect()
            if not m:
                raise RazerError(self.error or "mouse not connected")
            return fn(m)

    def _read_all(self, m: BasiliskV3):
        active, stages = m.get_dpi_stages()
        self.dev = {
            "connected": True,
            "firmware": m.firmware(),
            "serial": m.serial(),
            "dpi": list(m.get_dpi()),
            "stages": [list(s) for s in stages],
            "active_stage": active,
            "polling": m.get_polling(),
            "scroll": m.get_scroll(),
            "lighting": self._read_lighting(m),
        }
        self._base_dpi = self.dev["dpi"]
        self._clutch_hw = False

    def _read_lighting(self, m: BasiliskV3) -> dict:
        out = {}
        for z, led in LED_ZONES.items():
            spec = m.get_effect(led)
            spec["brightness"] = round(m.get_brightness(led) * 100 / 255)
            if not spec["colors"]:
                spec["colors"] = (self.dev.get("lighting", {}).get(z) or {}).get("colors") or ["#00b4ff"]
            out[z] = spec
        return out

    def snapshot(self) -> dict:
        return {**self.dev, "error": "" if self.dev.get("connected") else self.error,
                "active_profile": self.active_profile, "foreground": self.foreground, "paused": self.paused,
                "clutch": self._clutch_hw}

    def full_state(self) -> dict:
        if not self.dev.get("connected"):
            try:
                self.device(lambda m: None)
            except RazerError:
                pass
        cfg = self.config.snapshot()
        return {**self.snapshot(), "profiles": cfg["profiles"], "clutch_dpi": cfg.get("clutch_dpi"), "seq": self.last_seq}

    # ---------- the monitor: notices everything the mouse does by itself ----------
    def _monitor(self):
        tick = 0
        failures = 0
        while not self._stop.is_set():
            ui = time.time() - self._ui_seen < UI_ACTIVE_FOR
            self._wake.wait(FAST_TICK if ui else SLOW_TICK)
            self._wake.clear()
            if self._stop.is_set():
                return
            tick += 1
            try:
                with self.mouse_lock:
                    m = self._connect()
                    if not m:
                        continue
                    self._check_dpi(m)
                    if ui and tick % 4 == 0:
                        self._check_scroll(m)
                    if ui and tick % 25 == 0:
                        self._check_slow(m)
                failures = 0
            except (DeviceGone, OSError) as e:
                self._drop(e)
            except RazerError as e:
                # Usually another program talking to the mouse at the same moment.
                # Only give up on the connection if it keeps happening.
                failures += 1
                if failures >= 8:
                    self._drop(e)
                    failures = 0
            except Exception:
                pass

    def _check_dpi(self, m: BasiliskV3):
        active, stages = m.get_dpi_stages()
        stages = [list(s) for s in stages]
        dpi = list(m.get_dpi())
        d = self.dev
        own = time.time() - self._own_dpi_at < OWN_CHANGE_GRACE
        old_active, old_stages, old_dpi = d.get("active_stage"), d.get("stages"), d.get("dpi")
        if self._clutch_hw and active == old_active and stages == old_stages:
            return  # clutch held: the mouse reports its stored DPI, but the clutch DPI is what's live
        d.update(active_stage=active, stages=stages, dpi=dpi)
        if own:
            self._base_dpi = dpi
            if dpi != old_dpi or active != old_active:
                self.emit("dpi", dpi=dpi, active_stage=active, stages=stages, cause="app")
            return
        if active != old_active or stages != old_stages:
            # The DPI button cycles up and wraps to stage 1 after the last one.
            self._base_dpi = dpi
            if self._clutch_hw:
                self._clutch_hw = False
                self.emit("hw_button", name="clutch", down=False)
            self.emit("dpi", dpi=dpi, active_stage=active, stages=stages, cause="dpi_button")
            self.emit("hw_button", name="dpi", down=True)
            return
        if dpi != old_dpi:
            # Changed by something else (other software). The clutch doesn't show
            # up here at all: it only announces itself in a DPI report (below).
            self._base_dpi = dpi
            self.emit("dpi", dpi=dpi, active_stage=active, stages=stages, cause="device")

    # ---------- DPI reports: how the clutch (and DPI button) announce themselves ----------
    # The mouse sends report 05 02 <x hi> <x lo> <y hi> <y lo> on interface 1 whenever
    # the live DPI changes. Holding the clutch sends the clutch DPI; letting go sends
    # the DPI from before. The stored DPI we poll never changes for the clutch.
    def _start_reports(self):
        from .hid_win import enumerate_hid
        from .razer import BASILISK_V3_PID, RAZER_VID
        for i in enumerate_hid(RAZER_VID, BASILISK_V3_PID):
            p = i.path.lower()
            if "&mi_01&col" in p and i.usage_page == 0x0001 and i.usage == 0x0000:
                t = self._readers.get(p)
                if not (t and t.is_alive()):
                    t = threading.Thread(target=self._read_reports, args=(i.path,), name="dpi-reports", daemon=True)
                    self._readers[p] = t
                    t.start()

    def _read_reports(self, path: str):
        from .hid_win import HidReader
        try:
            r = HidReader(path)
        except OSError:
            return
        try:
            while not self._stop.is_set():
                data = r.read(64)
                if data is None:
                    return  # unplugged; restarted on reconnect
                if len(data) >= 6 and data[0] == 0x05 and data[1] == 0x02:
                    try:
                        self._on_dpi_report([(data[2] << 8) | data[3], (data[4] << 8) | data[5]])
                    except (RazerError, OSError):
                        pass
        finally:
            r.close()

    def _on_dpi_report(self, dpi: list):
        if self._clutch_hw:
            # While the clutch is held, the only report that matters is the release.
            # On release the mouse goes back to whatever DPI was live just before
            # it, and announces it. With our own clutch DPI that's *our* value
            # (we set it during the hold), so a report of our value means "released"
            # too. Repeats of the mouse's built-in clutch DPI are ignored.
            base = getattr(self, "_base_dpi", None)
            released = dpi == base or (self._clutch_override and dpi == self._own_dpi_value)
            if released:
                with self.mouse_lock:
                    self._clutch_hw = False
                    if self._clutch_override and self.mouse and base:
                        # The mouse came back to our clutch DPI, not yours: put yours back.
                        try:
                            self._set_own(self.mouse, base)
                        except RazerError:
                            self._set_own(self.mouse, base)
                        dpi = list(base)
                    self._clutch_override = False
                    self.dev["dpi"] = dpi
                    self.emit("hw_button", name="clutch", down=False)
                    self.emit("dpi", dpi=dpi, active_stage=self.dev.get("active_stage"),
                              stages=self.dev.get("stages"), cause="device")
            return
        if dpi == self._own_dpi_value and time.time() - self._own_dpi_at < OWN_CHANGE_GRACE:
            return  # the echo of a DPI we just set ourselves
        if time.time() - self._own_dpi_at < OWN_CHANGE_GRACE:
            return  # settling after one of our own changes; the poller handles it
        # If another program changed the DPI, it's still waiting for the mouse's
        # reply. Asking the mouse right now would overwrite that reply, so give it a moment.
        time.sleep(0.03)
        with self.mouse_lock:
            m = self.mouse
            if not m:
                return
            active, stages = m.get_dpi_stages()
            stages = [list(s) for s in stages]
            d = self.dev
            if active != d.get("active_stage") or stages != d.get("stages"):
                # The DPI button: a new stage.
                d.update(active_stage=active, stages=stages, dpi=dpi)
                self._base_dpi = dpi
                if self._clutch_hw:
                    self._clutch_hw = False
                    self.emit("hw_button", name="clutch", down=False)
                self.emit("dpi", dpi=dpi, active_stage=active, stages=stages, cause="dpi_button")
                self.emit("hw_button", name="dpi", down=True)
                return
            base = getattr(self, "_base_dpi", d.get("dpi"))
            if not self._clutch_hw and dpi != base:
                # Clutch pressed. The mouse jumped to its built-in clutch DPI;
                # if you picked your own, switch to that instead.
                self._clutch_hw = True
                d["clutch_hw_dpi"] = dpi[0]
                target = self.config.snapshot().get("clutch_dpi")
                if target and [target, target] != dpi:
                    self._set_own(m, [target, target])
                    self._clutch_override = True
                    dpi = [target, target]
                d["dpi"] = dpi
                self.emit("hw_button", name="clutch", down=True)
                self.emit("dpi", dpi=dpi, active_stage=active, stages=stages, cause="clutch")

    def _set_own(self, m: BasiliskV3, dpi):
        """Set the live DPI from inside the engine and remember it, so its echo is ignored."""
        self._own_dpi_value = list(dpi)
        self._own()
        m.set_dpi(*dpi)
        self._own()

    def _check_scroll(self, m: BasiliskV3):
        sc = m.get_scroll()
        old = self.dev.get("scroll")
        if sc != old:
            self.dev["scroll"] = sc
            if old and sc.get("free_spin") != old.get("free_spin"):
                self.emit("hw_button", name="scroll_mode")
            self.emit("scroll", scroll=sc)

    def _check_slow(self, m: BasiliskV3):
        # Lighting and polling only change by themselves through the profile
        # button underneath the mouse, so a slow check is enough.
        pol = m.get_polling()
        light = self._read_lighting(m)
        if pol != self.dev.get("polling") or light != self.dev.get("lighting"):
            self.dev.update(polling=pol, lighting=light)
            self.emit("settings", polling=pol, lighting=light)

    # ---------- settings from the window ----------
    def _own(self):
        self._own_dpi_at = time.time()

    def set_dpi(self, x: int, y: int):
        self._own_dpi_value = [x, y]
        self._own()
        self.device(lambda m: m.set_dpi(x, y))
        self._own()

    def set_stages(self, stages, active):
        sx, sy = stages[active - 1]
        self._own_dpi_value = [sx, sy]

        def w(m):
            m.set_dpi_stages(stages, active)
            m.set_dpi(sx, sy)
        self._own()
        self.device(w)
        self._own()
        self.dev.update(stages=[list(s) for s in stages], active_stage=active, dpi=[sx, sy])
        self.emit("dpi", dpi=[sx, sy], active_stage=active, stages=self.dev["stages"], cause="app")

    def set_polling(self, hz: int):
        self.device(lambda m: m.set_polling(hz))
        self.dev["polling"] = hz

    def set_scroll(self, key: str, on: bool):
        self.device(lambda m: m.set_scroll(key, on))
        self.dev.setdefault("scroll", {})[key] = on

    def set_lighting(self, zone: str, body: dict):
        spec = validate_lighting(zone, body)
        zones = list(LED_ZONES) if zone == "all" else [zone]

        def apply(m):
            for z in zones:
                led = ZONES[z]
                cols = [hex_rgb(c) for c in spec["colors"]]
                e = spec["effect"]
                if e == "off":
                    m.effect_none(led)
                elif e == "static":
                    m.effect_static(cols[0], led)
                elif e == "spectrum":
                    m.effect_spectrum(led)
                elif e == "wave":
                    m.effect_wave(1, (5 - spec["speed"]) * 0x14, led)
                m.set_brightness(round(spec["brightness"] * 255 / 100), led)

        self.device(apply)
        light = self.dev.setdefault("lighting", {})
        for z in zones:
            light[z] = dict(spec)

    def set_profiles(self, profiles):
        clean = validate_profiles(profiles)
        with self.config.lock:
            self.config.data["profiles"] = clean
            self.config.save()
        self._pick_profile(force=True)

    def set_clutch_dpi(self, dpi: int | None):
        """Your own clutch DPI (None = the mouse's built-in one). Applied on the next press."""
        with self.config.lock:
            self.config.data["clutch_dpi"] = dpi
            self.config.save()
        self.emit("clutch_setting", dpi=dpi)

    def set_paused(self, paused: bool):
        self.paused = paused
        self.emit("paused", paused=paused)

    # ---------- per-app profiles ----------
    def _refresh_bindings(self):
        cfg = self.config.snapshot()
        prof = next((p for p in cfg["profiles"] if p["id"] == self.active_profile), cfg["profiles"][0])
        self._bindings = dict(prof["bindings"])
        return prof

    def _pick_profile(self, force=False):
        exe, title = winput.foreground_app()
        if title == "Mouser" and not force:
            return  # our own window: keep whatever profile was active
        if exe:
            self.foreground = exe
        profiles = self.config.snapshot()["profiles"]
        match = next((p for p in profiles[1:] if self.foreground in p["apps"]), profiles[0])
        if match["id"] == self.active_profile and not force:
            return
        old = next((p for p in profiles if p["id"] == self.active_profile), None)
        changed = match["id"] != self.active_profile
        self.active_profile = match["id"]
        self._refresh_bindings()
        if not changed:
            return
        self.emit("profile", id=match["id"])
        try:
            if match.get("dpi"):
                self.set_dpi(match["dpi"], match["dpi"])
            elif old and old.get("dpi"):
                # Leaving a profile that forced a DPI: go back to the active stage.
                st = self.dev.get("stages") or []
                a = self.dev.get("active_stage") or 1
                if 0 < a <= len(st):
                    self.set_dpi(*st[a - 1])
        except RazerError:
            pass

    def _watch_apps(self):
        while not self._stop.wait(0.5):
            try:
                self._pick_profile()
            except Exception:
                pass

    # ---------- button remapping ----------
    def _on_button(self, name: str, down: bool, data: int) -> bool:
        """Runs on the hook thread: record, decide fast, do the work elsewhere."""
        if name in ("wheel_up", "wheel_down"):
            self.emit("wheel", dir="up" if name == "wheel_up" else "down")
        else:
            self.emit("button", name=name, down=down)
        if not down:
            action = self._held.pop(name, None)
            if action is None:
                return False
            self._jobs.put((name, False, action))
            return True
        if self.paused:
            return False
        action = self._bindings.get(name)
        if not action:
            return False
        if name not in CLICK_ONLY and name not in ("wheel_up", "wheel_down"):
            self._held[name] = action
        self._jobs.put((name, True, action))
        return True

    def _worker(self):
        while True:
            job = self._jobs.get()
            if job is None:
                return
            name, down, action = job
            try:
                self._run_action(name, down, action)
            except Exception:
                pass

    def _run_action(self, name, down, a):
        t = a["type"]
        click = name in CLICK_ONLY
        if t == "disabled":
            return
        if t == "mouse":
            winput.send_mouse_button(a["button"], True if click else down)
            if click:
                winput.send_mouse_button(a["button"], False)
        elif t == "keys":
            winput.send_keys(a["keys"], True if click else down)
            if click:
                winput.send_keys(a["keys"], False)
        elif t == "media":
            if down:
                winput.send_keys([MEDIA[a["key"]]], True)
                winput.send_keys([MEDIA[a["key"]]], False)
        elif t == "dpi" and down:
            self._step_dpi(a["mode"])
        elif t == "clutch":
            if down:
                cur = self.device(lambda m: m.get_dpi())
                self._clutch_restore = cur[0]
                self.set_dpi(a["dpi"], a["dpi"])
            elif self._clutch_restore:
                self.set_dpi(self._clutch_restore, self._clutch_restore)
                self._clutch_restore = None

    def _step_dpi(self, mode):
        st = self.dev.get("stages")
        if not st:
            st = [list(s) for s in self.device(lambda m: m.get_dpi_stages())[1]]
        active = self.dev.get("active_stage") or 1
        n = len(st)
        nxt = min(active + 1, n) if mode == "up" else max(active - 1, 1) if mode == "down" else active % n + 1
        self.set_stages([tuple(s) for s in st], nxt)


__all__ = ["Engine"]
