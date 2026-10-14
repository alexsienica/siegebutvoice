"""Global F8 key state (keyboard input uses PyDirectInput)."""

import ctypes


class WindowsState:
    def __init__(self):
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        self.user32.GetAsyncKeyState.restype = ctypes.c_short

    def f8_pressed(self):
        return bool(self.user32.GetAsyncKeyState(0x77) & 0x8000)
