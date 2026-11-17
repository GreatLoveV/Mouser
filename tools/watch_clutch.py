"""Diagnostic: shows everything the Basilisk V3 sends while you press buttons.

Watches three things at once, for N seconds (default 45):
  1. DPI and stage read from the mouse every 20 ms (does the clutch change them?)
  2. Raw Input from every Razer HID collection (mouse buttons incl. raw button
     bits, keyboard keys, consumer/vendor HID reports)
  3. Direct reads of the HID collections Windows lets us open
Read-only: nothing is written to the mouse.
"""
import ctypes
import ctypes.wintypes as wt
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mouser.hid_win import enumerate_hid  # noqa: E402
from mouser.razer import BasiliskV3, RazerError  # noqa: E402

DURATION = float(sys.argv[1]) if len(sys.argv) > 1 else 45
T0 = time.time()
lock = threading.Lock()


def log(src, msg):
    with lock:
        print(f"{time.time() - T0:6.2f}s  {src:8s} {msg}", flush=True)


# ---------- 1. DPI polling ----------
def poll_dpi():
    m = BasiliskV3.open()
    last = None
    while time.time() - T0 < DURATION:
        try:
            cur = (m.get_dpi(), m.get_dpi_stages()[0])
            if cur != last:
                log("dpi", f"dpi={cur[0]} stage={cur[1]}")
                last = cur
        except RazerError:
            pass
        time.sleep(0.02)
    m.close()


# ---------- 2. Raw Input ----------
user32 = ctypes.WinDLL("user32", use_last_error=True)
LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [("usUsagePage", wt.USHORT), ("usUsage", wt.USHORT), ("dwFlags", wt.DWORD), ("hwndTarget", wt.HWND)]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [("dwType", wt.DWORD), ("dwSize", wt.DWORD), ("hDevice", wt.HANDLE), ("wParam", wt.WPARAM)]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wt.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON), ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH),
                ("lpszMenuName", wt.LPCWSTR), ("lpszClassName", wt.LPCWSTR)]


user32.DefWindowProcW.restype = LRESULT
user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.CreateWindowExW.restype = wt.HWND
user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
user32.GetRawInputData.argtypes = [wt.HANDLE, wt.UINT, ctypes.c_void_p, ctypes.POINTER(wt.UINT), wt.UINT]
user32.GetRawInputDeviceInfoW.argtypes = [wt.HANDLE, wt.UINT, ctypes.c_void_p, ctypes.POINTER(wt.UINT)]
user32.RegisterRawInputDevices.argtypes = [ctypes.POINTER(RAWINPUTDEVICE), wt.UINT, wt.UINT]
user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
user32.SetTimer.argtypes = [wt.HWND, ctypes.c_size_t, wt.UINT, ctypes.c_void_p]

names: dict = {}
raw_buttons: dict = {}


def dev_name(h):
    if h not in names:
        n = wt.UINT(0)
        user32.GetRawInputDeviceInfoW(h, 0x20000007, None, ctypes.byref(n))
        buf = ctypes.create_unicode_buffer(n.value + 1)
        user32.GetRawInputDeviceInfoW(h, 0x20000007, buf, ctypes.byref(n))
        names[h] = buf.value.lower()
    return names[h]


def short(name):
    for part in ("mi_00", "mi_01", "mi_02", "mi_03"):
        if part in name:
            col = name.split("&col")[1][:2] if "&col" in name else ""
            return part + (f"/col{col}" if col else "")
    return "?"


def wndproc(hwnd, msg, wparam, lparam):
    if msg == 0x00FF:  # WM_INPUT
        size = wt.UINT(0)
        hdr = ctypes.sizeof(RAWINPUTHEADER)
        user32.GetRawInputData(lparam, 0x10000003, None, ctypes.byref(size), hdr)
        buf = ctypes.create_string_buffer(size.value)
        user32.GetRawInputData(lparam, 0x10000003, buf, ctypes.byref(size), hdr)
        h = RAWINPUTHEADER.from_buffer(buf)
        name = dev_name(h.hDevice) if h.hDevice else ""
        if "vid_1532" in name:
            data = buf.raw[hdr:]
            where = short(name)
            if h.dwType == 0:  # mouse
                flags = int.from_bytes(data[4:6], "little")
                bdata = int.from_bytes(data[6:8], "little", signed=True)
                rawb = int.from_bytes(data[8:12], "little")
                if flags or rawb != raw_buttons.get(where, 0):
                    log("mouse", f"{where} buttonFlags=0x{flags:04x} data={bdata} rawButtons=0x{rawb:08x}")
                raw_buttons[where] = rawb
            elif h.dwType == 1:  # keyboard
                make, kflags, _, vkey = (int.from_bytes(data[i:i + 2], "little") for i in (0, 2, 4, 6))
                log("keyboard", f"{where} vkey=0x{vkey:02x} make=0x{make:02x} {'up' if kflags & 1 else 'down'}")
            else:  # generic HID collection
                n = int.from_bytes(data[0:4], "little")
                cnt = int.from_bytes(data[4:8], "little")
                log("hid", f"{where} {cnt}x{n} bytes: {data[8:8 + n * cnt].hex(' ')}")
        return 0
    if msg == 0x0113:  # WM_TIMER
        if time.time() - T0 > DURATION:
            user32.PostQuitMessage(0)
        return 0
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


def raw_input_loop():
    proc = WNDPROC(wndproc)
    wc = WNDCLASSW()
    wc.lpfnWndProc = proc
    wc.lpszClassName = "MouserRawWatch"
    user32.RegisterClassW(ctypes.byref(wc))
    hwnd = user32.CreateWindowExW(0, wc.lpszClassName, "watch", 0, 0, 0, 0, 0, None, None, None, None)
    RIDEV_INPUTSINK, RIDEV_PAGEONLY = 0x100, 0x20
    want = [(0x01, 0x02, 0), (0x01, 0x06, 0), (0x0C, 0x01, 0), (0x01, 0x80, 0),
            (0xFF00, 0, RIDEV_PAGEONLY), (0x01, 0x00, 0)]
    for page, usage, extra in want:
        r = RAWINPUTDEVICE(page, usage, RIDEV_INPUTSINK | extra, hwnd)
        if not user32.RegisterRawInputDevices(ctypes.byref(r), 1, ctypes.sizeof(r)):
            log("setup", f"raw input page 0x{page:04x}/0x{usage:02x} not available (error {ctypes.get_last_error()})")
    user32.SetTimer(hwnd, 1, 250, None)
    msg = wt.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))


# ---------- 3. direct HID reads ----------
k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.CreateFileW.restype = wt.HANDLE
k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p, wt.DWORD, wt.DWORD, wt.HANDLE]
k32.ReadFile.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD), ctypes.c_void_p]


def read_collection(path, label):
    h = k32.CreateFileW(path, 0x80000000, 3, None, 3, 0, None)
    if h in (None, ctypes.c_void_p(-1).value) or h == -1:
        log("setup", f"{label}: can't open for reading (Windows owns it)")
        return
    log("setup", f"{label}: listening")
    buf = ctypes.create_string_buffer(256)
    n = wt.DWORD()
    while time.time() - T0 < DURATION:
        if k32.ReadFile(h, buf, 256, ctypes.byref(n), None) and n.value:
            log("read", f"{label}: {buf.raw[:n.value].hex(' ')}")


if __name__ == "__main__":
    log("setup", f"watching for {DURATION:.0f}s. Press the clutch a few times (hold ~1s each), then the other buttons once.")
    threading.Thread(target=poll_dpi, daemon=True).start()
    for i in enumerate_hid(0x1532, 0x0099):
        if i.usage_page not in (0x0001,) or i.usage not in (0x02, 0x06):
            threading.Thread(target=read_collection, args=(i.path, short(i.path.lower()) + f" page 0x{i.usage_page:04x}/0x{i.usage:02x}"), daemon=True).start()
    raw_input_loop()
    log("setup", "done")
