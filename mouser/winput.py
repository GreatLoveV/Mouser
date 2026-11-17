"""Windows input plumbing: low-level mouse hook, SendInput, foreground app."""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import threading

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WH_MOUSE_LL = 14
WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0201, 0x0202
WM_RBUTTONDOWN, WM_RBUTTONUP = 0x0204, 0x0205
WM_MBUTTONDOWN, WM_MBUTTONUP = 0x0207, 0x0208
WM_MOUSEWHEEL = 0x020A
WM_XBUTTONDOWN, WM_XBUTTONUP = 0x020B, 0x020C
WM_MOUSEHWHEEL = 0x020E
WM_QUIT = 0x0012
LLMHF_INJECTED = 0x01

ULONG_PTR = ctypes.c_size_t
LRESULT = ctypes.c_ssize_t


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("pt", wt.POINT), ("mouseData", wt.DWORD), ("flags", wt.DWORD), ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD), ("dwFlags", wt.DWORD), ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD), ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wt.DWORD), ("wParamL", wt.WORD), ("wParamH", wt.WORD)]


class _U(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("u", _U)]


HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wt.WPARAM, wt.LPARAM)
user32.SetWindowsHookExW.restype = wt.HHOOK
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wt.HINSTANCE, wt.DWORD]
user32.CallNextHookEx.restype = LRESULT
user32.CallNextHookEx.argtypes = [wt.HHOOK, ctypes.c_int, wt.WPARAM, wt.LPARAM]
user32.UnhookWindowsHookEx.argtypes = [wt.HHOOK]
user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
user32.PostThreadMessageW.argtypes = [wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.SendInput.argtypes = [wt.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.GetForegroundWindow.restype = wt.HWND
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.GetModuleHandleW.restype = wt.HMODULE
kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]

# Our own injected events carry this tag so the hook never re-maps them.
MOUSER_TAG = 0x4D53_5231

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP = 0x0001, 0x0002
MOUSEEVENTF = {
    "left": (0x0002, 0x0004, 0), "right": (0x0008, 0x0010, 0), "middle": (0x0020, 0x0040, 0),
    "back": (0x0080, 0x0100, 1), "forward": (0x0080, 0x0100, 2),
}
MOUSEEVENTF_WHEEL, MOUSEEVENTF_HWHEEL = 0x0800, 0x1000

EXTENDED_VKS = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x5B, 0x5C, 0x6F, 0xA3, 0xA5,
                0xAD, 0xAE, 0xAF, 0xB0, 0xB1, 0xB2, 0xB3, 0xA6, 0xA7, 0xA8, 0xAC}


def _send(inputs: list[INPUT]) -> None:
    arr = (INPUT * len(inputs))(*inputs)
    user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


def send_mouse_button(name: str, down: bool) -> None:
    dflag, uflag, xdata = MOUSEEVENTF[name]
    i = INPUT(type=INPUT_MOUSE)
    i.u.mi = MOUSEINPUT(0, 0, xdata, dflag if down else uflag, 0, MOUSER_TAG)
    _send([i])


def send_wheel(delta: int, horizontal: bool = False) -> None:
    i = INPUT(type=INPUT_MOUSE)
    i.u.mi = MOUSEINPUT(0, 0, ctypes.c_uint32(delta).value, MOUSEEVENTF_HWHEEL if horizontal else MOUSEEVENTF_WHEEL, 0, MOUSER_TAG)
    _send([i])


def _key(vk: int, up: bool) -> INPUT:
    i = INPUT(type=INPUT_KEYBOARD)
    flags = (KEYEVENTF_KEYUP if up else 0) | (KEYEVENTF_EXTENDEDKEY if vk in EXTENDED_VKS else 0)
    i.u.ki = KEYBDINPUT(vk, 0, flags, 0, MOUSER_TAG)
    return i


def send_keys(vks: list[int], down: bool) -> None:
    """Press (in order) or release (in reverse order) a key chord."""
    seq = [_key(v, False) for v in vks] if down else [_key(v, True) for v in reversed(vks)]
    _send(seq)


user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]


def foreground_app() -> tuple[str, str]:
    """(exe name, window title) of the window in front."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return "", ""
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, buf, 256)
    return foreground_exe(hwnd), buf.value


def foreground_exe(hwnd=None) -> str:
    hwnd = hwnd or user32.GetForegroundWindow()
    if not hwnd:
        return ""
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h = kernel32.OpenProcess(0x1000, False, pid.value)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        n = wt.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
            return os.path.basename(buf.value).lower()
        return ""
    finally:
        kernel32.CloseHandle(h)


class MouseHook:
    """Runs a WH_MOUSE_LL hook on its own thread.

    `handler(button, down, data) -> bool` decides per event; True swallows it.
    Buttons: left, right, middle, back, forward, wheel_up, wheel_down,
    tilt_left, tilt_right. The handler must return fast.
    """

    def __init__(self, handler):
        self.handler = handler
        self._thread: threading.Thread | None = None
        self._tid = 0
        self._proc = HOOKPROC(self._callback)
        self._hook = None
        self.ready = threading.Event()

    def _callback(self, code, wparam, lparam):
        if code == 0 and wparam != 0x0200:  # skip WM_MOUSEMOVE quickly
            info = ctypes.cast(lparam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            if not (info.flags & LLMHF_INJECTED and info.dwExtraInfo == MOUSER_TAG):
                ev = _decode(wparam, info.mouseData)
                if ev is not None:
                    try:
                        if self.handler(*ev):
                            return 1
                    except Exception:  # never break the user's mouse
                        pass
        return user32.CallNextHookEx(None, code, wparam, lparam)

    def _run(self):
        self._tid = kernel32.GetCurrentThreadId()
        self._hook = user32.SetWindowsHookExW(WH_MOUSE_LL, self._proc, kernel32.GetModuleHandleW(None), 0)
        self.ready.set()
        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            pass
        if self._hook:
            user32.UnhookWindowsHookEx(self._hook)

    def start(self):
        self._thread = threading.Thread(target=self._run, name="mouse-hook", daemon=True)
        self._thread.start()
        self.ready.wait(2)

    def stop(self):
        if self._tid:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)


def _decode(wparam: int, data: int):
    hi = ctypes.c_short((data >> 16) & 0xFFFF).value
    if wparam == WM_LBUTTONDOWN: return ("left", True, 0)
    if wparam == WM_LBUTTONUP: return ("left", False, 0)
    if wparam == WM_RBUTTONDOWN: return ("right", True, 0)
    if wparam == WM_RBUTTONUP: return ("right", False, 0)
    if wparam == WM_MBUTTONDOWN: return ("middle", True, 0)
    if wparam == WM_MBUTTONUP: return ("middle", False, 0)
    if wparam in (WM_XBUTTONDOWN, WM_XBUTTONUP):
        return ("back" if hi == 1 else "forward", wparam == WM_XBUTTONDOWN, 0)
    if wparam == WM_MOUSEWHEEL:
        return ("wheel_up" if hi > 0 else "wheel_down", True, hi)
    if wparam == WM_MOUSEHWHEEL:
        return ("tilt_right" if hi > 0 else "tilt_left", True, hi)
    return None
