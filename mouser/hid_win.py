"""Minimal Windows HID access through ctypes (hid.dll + setupapi.dll).

No third-party packages: enumerates HID interfaces, reads their capabilities,
and sends/receives feature reports. Mouse and keyboard collections are opened
with zero access rights, which Windows allows for feature reports.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
from dataclasses import dataclass

_hid = ctypes.WinDLL("hid")
_setupapi = ctypes.WinDLL("setupapi")
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wt.DWORD), ("Data2", wt.WORD), ("Data3", wt.WORD), ("Data4", ctypes.c_ubyte * 8)]


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("InterfaceClassGuid", GUID), ("Flags", wt.DWORD), ("Reserved", ctypes.c_void_p)]


class HIDD_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Size", wt.ULONG), ("VendorID", wt.USHORT), ("ProductID", wt.USHORT), ("VersionNumber", wt.USHORT)]


class HIDP_CAPS(ctypes.Structure):
    _fields_ = [
        ("Usage", wt.USHORT), ("UsagePage", wt.USHORT),
        ("InputReportByteLength", wt.USHORT), ("OutputReportByteLength", wt.USHORT),
        ("FeatureReportByteLength", wt.USHORT), ("Reserved", wt.USHORT * 17),
        ("NumberLinkCollectionNodes", wt.USHORT), ("NumberInputButtonCaps", wt.USHORT),
        ("NumberInputValueCaps", wt.USHORT), ("NumberInputDataIndices", wt.USHORT),
        ("NumberOutputButtonCaps", wt.USHORT), ("NumberOutputValueCaps", wt.USHORT),
        ("NumberOutputDataIndices", wt.USHORT), ("NumberFeatureButtonCaps", wt.USHORT),
        ("NumberFeatureValueCaps", wt.USHORT), ("NumberFeatureDataIndices", wt.USHORT),
    ]


DIGCF_PRESENT = 0x02
DIGCF_DEVICEINTERFACE = 0x10
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
FILE_SHARE_READ_WRITE = 0x03
OPEN_EXISTING = 3
GENERIC_READ_WRITE = 0x80000000 | 0x40000000

_setupapi.SetupDiGetClassDevsW.restype = ctypes.c_void_p
_setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(GUID), wt.LPCWSTR, wt.HWND, wt.DWORD]
_setupapi.SetupDiEnumDeviceInterfaces.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(GUID), wt.DWORD, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA)]
_setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [ctypes.c_void_p, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA), ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
_setupapi.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]
_k32.CreateFileW.restype = wt.HANDLE
_k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p, wt.DWORD, wt.DWORD, wt.HANDLE]
_k32.CloseHandle.argtypes = [wt.HANDLE]
_hid.HidD_GetAttributes.argtypes = [wt.HANDLE, ctypes.POINTER(HIDD_ATTRIBUTES)]
_hid.HidD_GetPreparsedData.argtypes = [wt.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
_hid.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
_hid.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.POINTER(HIDP_CAPS)]
_hid.HidD_SetFeature.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.ULONG]
_hid.HidD_GetFeature.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.ULONG]


@dataclass
class HidInterface:
    path: str
    vid: int
    pid: int
    usage_page: int
    usage: int
    feature_len: int


def _open(path: str, access: int = 0) -> int | None:
    h = _k32.CreateFileW(path, access, FILE_SHARE_READ_WRITE, None, OPEN_EXISTING, 0, None)
    if h in (None, INVALID_HANDLE_VALUE) or h == -1:
        return None
    return h


def _paths() -> list[str]:
    guid = GUID()
    _hid.HidD_GetHidGuid(ctypes.byref(guid))
    info = _setupapi.SetupDiGetClassDevsW(ctypes.byref(guid), None, None, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
    out: list[str] = []
    if info in (None, INVALID_HANDLE_VALUE):
        return out
    try:
        i = 0
        while True:
            ifd = SP_DEVICE_INTERFACE_DATA()
            ifd.cbSize = ctypes.sizeof(ifd)
            if not _setupapi.SetupDiEnumDeviceInterfaces(info, None, ctypes.byref(guid), i, ctypes.byref(ifd)):
                break
            i += 1
            need = wt.DWORD()
            _setupapi.SetupDiGetDeviceInterfaceDetailW(info, ctypes.byref(ifd), None, 0, ctypes.byref(need), None)
            buf = ctypes.create_string_buffer(need.value)
            # cbSize of SP_DEVICE_INTERFACE_DETAIL_DATA_W: 8 on 64-bit, 6 on 32-bit
            ctypes.c_uint32.from_buffer(buf).value = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
            if _setupapi.SetupDiGetDeviceInterfaceDetailW(info, ctypes.byref(ifd), buf, need, None, None):
                out.append(ctypes.wstring_at(ctypes.addressof(buf) + 4))
    finally:
        _setupapi.SetupDiDestroyDeviceInfoList(info)
    return out


def enumerate_hid(vid: int | None = None, pid: int | None = None) -> list[HidInterface]:
    found: list[HidInterface] = []
    for path in _paths():
        low = path.lower()
        if vid is not None and f"vid_{vid:04x}" not in low:
            continue
        if pid is not None and f"pid_{pid:04x}" not in low:
            continue
        h = _open(path)
        if h is None:
            continue
        try:
            attrs = HIDD_ATTRIBUTES()
            attrs.Size = ctypes.sizeof(attrs)
            if not _hid.HidD_GetAttributes(h, ctypes.byref(attrs)):
                continue
            pre = ctypes.c_void_p()
            caps = HIDP_CAPS()
            if _hid.HidD_GetPreparsedData(h, ctypes.byref(pre)):
                _hid.HidP_GetCaps(pre, ctypes.byref(caps))
                _hid.HidD_FreePreparsedData(pre)
            found.append(HidInterface(path, attrs.VendorID, attrs.ProductID, caps.UsagePage, caps.Usage, caps.FeatureReportByteLength))
        finally:
            _k32.CloseHandle(h)
    return found


_k32.ReadFile.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
_k32.CancelIoEx.argtypes = [wt.HANDLE, ctypes.c_void_p]


class HidReader:
    """Blocking reader for a HID collection's input reports (one we're allowed to read)."""

    def __init__(self, path: str):
        self.handle = _open(path, 0x80000000)  # GENERIC_READ
        if self.handle is None:
            raise OSError(f"cannot open HID interface for reading (error {ctypes.get_last_error()})")

    def read(self, size: int = 64) -> bytes | None:
        """Waits for the next report. None means the device went away (or close() was called)."""
        buf = ctypes.create_string_buffer(size)
        n = wt.DWORD()
        if not _k32.ReadFile(self.handle, buf, size, ctypes.byref(n), None):
            return None
        return buf.raw[:n.value]

    def close(self) -> None:
        if self.handle is not None:
            _k32.CancelIoEx(self.handle, None)
            _k32.CloseHandle(self.handle)
            self.handle = None


class HidDevice:
    """An open HID interface used only for feature reports."""

    def __init__(self, path: str):
        self.path = path
        self.handle = _open(path, 0) or _open(path, GENERIC_READ_WRITE)
        if self.handle is None:
            raise OSError(f"cannot open HID interface (error {ctypes.get_last_error()})")

    def set_feature(self, data: bytes) -> bool:
        buf = ctypes.create_string_buffer(bytes(data), len(data))
        return bool(_hid.HidD_SetFeature(self.handle, buf, len(data)))

    def get_feature(self, report_id: int, length: int) -> bytes | None:
        buf = ctypes.create_string_buffer(length)
        buf[0] = report_id
        if not _hid.HidD_GetFeature(self.handle, buf, length):
            return None
        return buf.raw

    def close(self) -> None:
        if self.handle is not None:
            _k32.CloseHandle(self.handle)
            self.handle = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
