<p align="center">
  <img src="web/icon.svg" width="112" alt="Mouser icon: a Basilisk V3 seen from above with a glowing wheel and underglow">
</p>

<h1 align="center">Mouser</h1>

<p align="center">
  A small, fast control app for the <b>Razer Basilisk V3</b>, so you don't need Razer Synapse.<br>
  DPI, lighting, polling rate, scroll wheel, button remapping and per-app profiles, with a live drawing of the mouse that reacts to everything you do.
</p>

<p align="center">
  Windows&nbsp;10/11 · Python&nbsp;3.10+ · no dependencies · no account · nothing leaves your PC
</p>

---

## Why

Synapse is heavy. It needs an account, runs several background services and takes a while to open. Mouser is about 3,000 lines of Python and plain JavaScript. It talks to the mouse directly over USB HID and opens in under a second.

It's built for one mouse (USB `1532:0099`) and it's honest about what that mouse's firmware will and won't do.

## Features

- **Live mirror.** The drawing of the mouse lights up as you press, scroll and tilt. It also follows the buttons Windows never sees: the DPI button, the sensitivity clutch and the scroll-mode button.
- **DPI stages.**
  - 1 to 5 stages, from 100 to 26,000 DPI, with optional separate X/Y values.
  - Changes save to the mouse as you edit.
  - Pressing the DPI button on the mouse moves the selected stage in the app.
- **Sensitivity clutch.** Keep the built-in 400 DPI, or pick your own clutch DPI. It drops while you hold the thumb button and comes back when you let go.
- **Lighting** for each zone (scroll wheel, logo, underglow), with the drawing glowing the same color:
  - off, static, spectrum or wave
  - adjustable speed and brightness
- **Polling rate:** 125, 500 or 1000 Hz.
- **Scroll wheel:** smart-reel, acceleration and free-spin.
- **Button remapping** for right click, wheel click, back, forward, and tilt left and right. Each button can be set to:
  - disabled, or another mouse button
  - a keyboard shortcut (captured by pressing it), or a media key
  - DPI up, DPI down or DPI cycle
  - a clutch you hold down
- **Per-app profiles.** Mouser switches bindings, and optionally DPI, based on the program in front.
- **Tray icon.** Click it to open the window. Its menu has Pause remapping and Quit. Closing the window keeps the remaps running.
- **Light and dark themes** that follow Windows, with full keyboard navigation and support for reduced motion.

Hardware settings (DPI, lighting, polling, scroll) are stored on the mouse itself, so they keep working on any PC. Remaps and profiles are software and need Mouser running.

## Getting started

```bash
git clone https://github.com/GreatLoveV/Mouser.git
```

Then double-click **`Mouser.cmd`**. To see log output, run it from a terminal instead:

```bash
python run.pyw
```

Close Razer Synapse first if it's running, because the two will fight over the mouse.

If you want a shortcut with the icon, create one that points to `pythonw.exe -I "<path>\run.pyw"` and set its icon to `web\mouser.ico`.

Settings are saved in `%APPDATA%\Mouser\config.json`.

## What the Basilisk V3 can't do (yet)

| Not supported | Why |
|---|---|
| Onboard button remaps (remaps that work without Mouser running) | The protocol isn't documented for this model. |
| Breathing and reactive lighting | Firmware 1.00 refuses them in every packet layout tried. |
| Remapping the DPI, scroll-mode and clutch buttons | The mouse handles these internally and never reports them to Windows. |
| Remapping left click | Deliberately not offered, so a bad setting can't lock you out. |

## How it works

```
mouser/hid_win.py   HID enumeration, feature and input reports (ctypes → hid.dll)
mouser/razer.py     Razer 90-byte report protocol, Basilisk V3 commands
mouser/winput.py    low-level mouse hook, SendInput, foreground program
mouser/engine.py    device monitor, live events, clutch, profiles, remap actions
mouser/config.py    config file and input validation
mouser/server.py    local HTTP API for the UI (127.0.0.1 only)
mouser/tray.py      tray icon
mouser/app.py       single instance, starts everything, opens the window
web/                the UI: plain HTML, CSS and JS, no build step
tools/              hardware probes, end-to-end tests, icon builder
```

The window is your installed Edge or Chrome in `--app` mode with its own profile, pointed at the local server. You don't need Electron or anything else installed.

### Protocol notes

These may help anyone else writing tools for this mouse.

- **Control channel:** HID interface 3 (`MI_03`, 91-byte feature reports), transaction ID `0x1F`.
- **Status byte:** `0x02` ok, `0x01` busy, `0x03` failed, `0x05` not supported.
- **Lighting zones:** `0x01` scroll wheel, `0x04` logo, `0x0A` underglow.
- **Wave effect:** `0F:02` with args `[store, led, 0x04, direction, speed, 0]`.
- **Clutch:**
  - It never changes the stored DPI, so polling `04:85` misses it.
  - The mouse announces every live DPI change as input report `05 02 <x hi> <x lo> <y hi> <y lo>` on interface 1 (`MI_01`, usage page 1, usage 0).
  - It reports 400 on press and the previous DPI on release. If you set a DPI while it's held, it reports that value on release instead.

## Security

The local server can change hardware settings and send keystrokes, so it's locked down:

- It listens on `127.0.0.1` only.
- Each launch creates a random token. The window gets it in the URL fragment, and every API call must send it back in a header.
- `Host` and `Origin` checks block DNS rebinding and other websites. The custom header forces a CORS preflight, which is never approved.
- Requests are JSON only, capped at 64 KB, and every field is validated.
- Static files come from a fixed allow-list.
- The CSP is strict: `default-src 'none'`, with no inline script or style.
- There's no "launch program" action, so no remap can run arbitrary commands.

## Rebuilding the icon

`web/icon.svg` is the source. The script below renders every size with headless Chrome or Edge and writes `web/mouser.ico`:

```bash
python tools/build_icon.py
```

## Disclaimer

This is an unofficial personal project, not affiliated with or endorsed by Razer. "Razer" and "Basilisk" are trademarks of Razer Inc. Use it at your own risk. It sends the same kinds of commands Synapse does, but it hasn't been tested on other models or firmware versions.
