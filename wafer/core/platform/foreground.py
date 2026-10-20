import ctypes
import sys

from ..logs import AppLogger

SW_RESTORE = 9


def user32_window_functions():
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsIconic.restype = wintypes.BOOL
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    return user32


def activate_window(hwnd: int) -> bool:
    if sys.platform != "win32" or hwnd == 0:
        return False
    user32 = user32_window_functions()
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    activated = bool(user32.SetForegroundWindow(hwnd))
    if not activated:
        AppLogger.debug(f"SetForegroundWindow failed: hwnd={hwnd}")
    return activated
