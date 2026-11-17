"""Inject harmless mouse input (wheel scroll or wheel tilt) to test the live display."""
import ctypes
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mouser.winput import INPUT, INPUT_MOUSE, MOUSEINPUT, user32  # noqa: E402

kind = sys.argv[1]
flag, delta = {"wheel_down": (0x0800, -120), "wheel_up": (0x0800, 120), "tilt_left": (0x1000, -120), "tilt_right": (0x1000, 120)}[kind]
time.sleep(float(sys.argv[2]) if len(sys.argv) > 2 else 0)
i = INPUT(type=INPUT_MOUSE)
i.u.mi = MOUSEINPUT(0, 0, ctypes.c_uint32(delta).value, flag, 0, 0)
user32.SendInput(1, (INPUT * 1)(i), ctypes.sizeof(INPUT))
print("sent", kind)
