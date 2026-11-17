"""Notification-area icon (ctypes, no dependencies): click to open, menu to pause or quit."""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import threading

user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32")
kernel32 = ctypes.WinDLL("kernel32")

WM_USER = 0x0400
WM_TRAY = WM_USER + 20
WM_COMMAND = 0x0111
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_LBUTTONUP, WM_RBUTTONUP = 0x0202, 0x0205
NIM_ADD, NIM_DELETE = 0, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP = 1, 2, 4
ID_OPEN, ID_PAUSE, ID_QUIT = 1, 2, 3
LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wt.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON), ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH),
                ("lpszMenuName", wt.LPCWSTR), ("lpszClassName", wt.LPCWSTR)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("hWnd", wt.HWND), ("uID", wt.UINT), ("uFlags", wt.UINT),
                ("uCallbackMessage", wt.UINT), ("hIcon", wt.HICON), ("szTip", wt.WCHAR * 128)]


user32.DefWindowProcW.restype = LRESULT
user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.CreateWindowExW.restype = wt.HWND
user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
user32.LoadIconW.restype = wt.HICON
user32.LoadIconW.argtypes = [wt.HINSTANCE, ctypes.c_void_p]
user32.CreatePopupMenu.restype = wt.HMENU
user32.AppendMenuW.argtypes = [wt.HMENU, wt.UINT, ctypes.c_size_t, wt.LPCWSTR]
user32.TrackPopupMenu.argtypes = [wt.HMENU, wt.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HWND, ctypes.c_void_p]
user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
user32.DestroyMenu.argtypes = [wt.HMENU]
user32.DestroyWindow.argtypes = [wt.HWND]
shell32.Shell_NotifyIconW.argtypes = [wt.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
kernel32.GetModuleHandleW.restype = wt.HMODULE
kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]


class Tray:
    def __init__(self, on_open, on_toggle_pause, is_paused, on_quit):
        self.on_open, self.on_toggle_pause, self.is_paused, self.on_quit = on_open, on_toggle_pause, is_paused, on_quit
        self.hwnd = None
        self._proc = WNDPROC(self._wndproc)

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_TRAY:
            if lparam == WM_LBUTTONUP:
                self.on_open()
            elif lparam == WM_RBUTTONUP:
                self._menu()
            return 0
        if msg == WM_COMMAND:
            cmd = wparam & 0xFFFF
            if cmd == ID_OPEN:
                self.on_open()
            elif cmd == ID_PAUSE:
                self.on_toggle_pause()
            elif cmd == ID_QUIT:
                self.on_quit()
            return 0
        if msg == WM_CLOSE:
            user32.DestroyWindow(hwnd)
            return 0
        if msg == WM_DESTROY:
            self._remove()
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _menu(self):
        m = user32.CreatePopupMenu()
        user32.AppendMenuW(m, 0, ID_OPEN, "Open Mouser")
        user32.AppendMenuW(m, 0, ID_PAUSE, "Resume button remapping" if self.is_paused() else "Pause button remapping")
        user32.AppendMenuW(m, 0x800, 0, None)  # separator
        user32.AppendMenuW(m, 0, ID_QUIT, "Quit Mouser")
        pt = wt.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        user32.SetForegroundWindow(self.hwnd)
        user32.TrackPopupMenu(m, 0x0008 | 0x0020, pt.x, pt.y, 0, self.hwnd, None)  # TPM_RIGHTALIGN | TPM_BOTTOMALIGN
        user32.PostMessageW(self.hwnd, 0, 0, 0)  # WM_NULL: lets the menu close when you click elsewhere
        user32.DestroyMenu(m)

    def _nid(self):
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(nid)
        nid.hWnd = self.hwnd
        nid.uID = 1
        return nid

    def _remove(self):
        if self.hwnd:
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid()))

    def run(self):
        """Blocks running the message loop. Call from the main thread."""
        hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSW()
        wc.lpfnWndProc = self._proc
        wc.hInstance = hinst
        wc.lpszClassName = "MouserTrayWindow"
        user32.RegisterClassW(ctypes.byref(wc))
        self.hwnd = user32.CreateWindowExW(0, wc.lpszClassName, "Mouser", 0, 0, 0, 0, 0, None, None, hinst, None)
        nid = self._nid()
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_TRAY
        # The mouse icon from Windows' own Mouse settings, falling back to the generic app icon.
        # Mouser's own icon (web/mouser.ico, built by tools/build_icon.py) at the tray's size,
        # falling back to the system mouse icon if the file is missing.
        user32.LoadImageW.restype = wt.HANDLE
        user32.LoadImageW.argtypes = [wt.HINSTANCE, wt.LPCWSTR, wt.UINT, ctypes.c_int, ctypes.c_int, wt.UINT]
        ico = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "mouser.ico")
        icon = None
        if os.path.isfile(ico):
            icon = user32.LoadImageW(None, ico, 1, user32.GetSystemMetrics(49), user32.GetSystemMetrics(50), 0x10)
        if not icon:
            shell32.ExtractIconW.restype = wt.HICON
            shell32.ExtractIconW.argtypes = [wt.HINSTANCE, wt.LPCWSTR, wt.UINT]
            icon = shell32.ExtractIconW(hinst, os.path.expandvars(r"%SystemRoot%\System32\main.cpl"), 0)
        nid.hIcon = icon if icon and icon > 1 else user32.LoadIconW(None, ctypes.c_void_p(32512))
        nid.szTip = "Mouser - Basilisk V3"
        shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid))
        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def close(self):
        if self.hwnd:
            user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)


def run_in_thread(tray: Tray) -> threading.Thread:
    t = threading.Thread(target=tray.run, name="tray", daemon=True)
    t.start()
    return t
