import ctypes
import sys

from ..logs import AppLogger

SW_RESTORE = 9


def activate_window(hwnd: int) -> bool:
    if sys.platform != "win32" or hwnd == 0:
        return False
    user32 = ctypes.windll.user32
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    activated = bool(user32.SetForegroundWindow(hwnd))
    if not activated:
        AppLogger.debug(f"SetForegroundWindow failed: hwnd={hwnd}")
    return activated
