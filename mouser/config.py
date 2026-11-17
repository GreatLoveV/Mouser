"""Profiles, bindings and lighting presets, stored in %APPDATA%\\Mouser\\config.json.

Everything coming from the UI passes through `validate_*` before it is used
or saved, so a bad request can never write junk into the config.
"""
from __future__ import annotations

import copy
import json
import os
import re
import threading

APP_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Mouser")
CONFIG_PATH = os.path.join(APP_DIR, "config.json")

# Buttons the app may remap. Left click is deliberately excluded so you can
# never lock yourself out of your own mouse.
REMAPPABLE = ["right", "middle", "back", "forward", "tilt_left", "tilt_right"]
HOLDABLE = {"right", "middle", "back", "forward"}  # buttons that send a release
MOUSE_TARGETS = ["left", "right", "middle", "back", "forward"]
MEDIA = {"play_pause": 0xB3, "next": 0xB0, "prev": 0xB1, "vol_up": 0xAF, "vol_down": 0xAE, "mute": 0xAD}
ZONES = {"all": 0x00, "scroll": 0x01, "logo": 0x04, "underglow": 0x0A}
# Breathing and reactive were tested on firmware v1.00 and the mouse refuses them
# ("not supported") in every packet layout, so they're not offered.
EFFECTS = ["off", "static", "spectrum", "wave"]
EXE_RE = re.compile(r"^[\w .()+\-]{1,80}\.exe$", re.IGNORECASE)
HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class Invalid(ValueError):
    pass


DEFAULT_CONFIG = {
    "version": 1,
    "profiles": [
        {"id": "default", "name": "Everywhere", "apps": [], "bindings": {}, "dpi": None},
    ],
    "clutch_dpi": None,  # None = the clutch uses the mouse's built-in DPI
}


def _int(v, lo, hi, name):
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise Invalid(f"{name} must be a whole number from {lo} to {hi}")
    return v


def _str(v, maxlen, name):
    if not isinstance(v, str) or not 0 < len(v.strip()) <= maxlen:
        raise Invalid(f"{name} must be text up to {maxlen} characters")
    return v.strip()


def validate_action(a, button: str) -> dict:
    if not isinstance(a, dict):
        raise Invalid("action must be an object")
    t = a.get("type")
    if t in ("default", "disabled"):
        return {"type": t}
    if t == "mouse":
        b = a.get("button")
        if b not in MOUSE_TARGETS:
            raise Invalid("unknown mouse button")
        return {"type": "mouse", "button": b}
    if t == "keys":
        keys = a.get("keys")
        if not isinstance(keys, list) or not 1 <= len(keys) <= 4:
            raise Invalid("a shortcut has 1 to 4 keys")
        keys = [_int(k, 1, 254, "key code") for k in keys]
        label = _str(a.get("label") or "Shortcut", 40, "label")
        return {"type": "keys", "keys": keys, "label": label}
    if t == "media":
        if a.get("key") not in MEDIA:
            raise Invalid("unknown media key")
        return {"type": "media", "key": a["key"]}
    if t == "dpi":
        if a.get("mode") not in ("up", "down", "cycle"):
            raise Invalid("DPI action must be up, down or cycle")
        return {"type": "dpi", "mode": a["mode"]}
    if t == "clutch":
        if button not in HOLDABLE:
            raise Invalid("sensitivity clutch needs a button you can hold")
        return {"type": "clutch", "dpi": _int(a.get("dpi"), 100, 26000, "clutch DPI")}
    raise Invalid("unknown action type")


def validate_profile(p) -> dict:
    if not isinstance(p, dict):
        raise Invalid("profile must be an object")
    pid = p.get("id")
    if not isinstance(pid, str) or not re.fullmatch(r"[a-z0-9-]{1,40}", pid):
        raise Invalid("bad profile id")
    name = _str(p.get("name"), 40, "profile name")
    apps = p.get("apps") or []
    if not isinstance(apps, list) or len(apps) > 30:
        raise Invalid("apps must be a list (max 30)")
    clean_apps = []
    for exe in apps:
        if not isinstance(exe, str) or not EXE_RE.match(exe.strip()):
            raise Invalid(f"'{exe}' is not a program name like game.exe")
        clean_apps.append(exe.strip().lower())
    bindings = p.get("bindings") or {}
    if not isinstance(bindings, dict):
        raise Invalid("bindings must be an object")
    clean_b = {}
    for btn, act in bindings.items():
        if btn not in REMAPPABLE:
            raise Invalid(f"'{btn}' cannot be remapped")
        act = validate_action(act, btn)
        if act["type"] != "default":
            clean_b[btn] = act
    dpi = p.get("dpi")
    if dpi is not None:
        dpi = _int(dpi, 100, 26000, "profile DPI")
    return {"id": pid, "name": name, "apps": clean_apps, "bindings": clean_b, "dpi": dpi}


def validate_profiles(lst) -> list:
    if not isinstance(lst, list) or not 1 <= len(lst) <= 20:
        raise Invalid("1 to 20 profiles")
    out = [validate_profile(p) for p in lst]
    if out[0]["id"] != "default":
        raise Invalid("the first profile must be the everywhere profile")
    out[0]["apps"] = []
    if len({p["id"] for p in out}) != len(out):
        raise Invalid("profile ids must be unique")
    return out


def validate_lighting(zone, body) -> dict:
    if zone not in ZONES:
        raise Invalid("unknown zone")
    effect = body.get("effect")
    if effect not in EFFECTS:
        raise Invalid("unknown effect")
    colors = body.get("colors") or []
    if not isinstance(colors, list) or len(colors) > 1 or not all(isinstance(c, str) and HEX_RE.match(c) for c in colors):
        raise Invalid("color must be one #rrggbb value")
    speed = _int(body.get("speed", 2), 1, 4, "speed")
    brightness = _int(body.get("brightness", 70), 0, 100, "brightness")
    return {"effect": effect, "colors": [c.lower() for c in colors] or ["#00b4ff"], "speed": speed, "brightness": brightness}


class Config:
    def __init__(self):
        self.lock = threading.RLock()
        self.data = copy.deepcopy(DEFAULT_CONFIG)
        self.load()

    def load(self):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                raw = json.load(f)
            profiles = validate_profiles(raw.get("profiles"))
            # Lighting lives on the mouse and is read from it; only app settings are stored here.
            clutch = raw.get("clutch_dpi")
            if clutch is not None:
                clutch = _int(clutch, 100, 26000, "clutch DPI")
            self.data = {"version": 1, "profiles": profiles, "clutch_dpi": clutch}
        except FileNotFoundError:
            pass
        except (ValueError, OSError, AttributeError):
            # Keep a copy of the unreadable file instead of silently losing it.
            try:
                os.replace(CONFIG_PATH, CONFIG_PATH + ".broken")
            except OSError:
                pass

    def save(self):
        with self.lock:
            os.makedirs(APP_DIR, exist_ok=True)
            tmp = CONFIG_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
            os.replace(tmp, CONFIG_PATH)

    def snapshot(self) -> dict:
        with self.lock:
            return copy.deepcopy(self.data)
