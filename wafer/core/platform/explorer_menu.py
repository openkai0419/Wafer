import sys

from ..common.paths import get_launcher_path
from .process import AppProcess

if sys.platform == "win32":
    import winreg

MENU_KEY = r"Software\Classes\*\shell\Wafer"
MENU_LABEL = "Open with Wafer"


def launch_command() -> str | None:
    if sys.platform != "win32":
        return None
    launcher = get_launcher_path()
    if launcher:
        return f'"{launcher}" "%1"'
    exe, script = AppProcess.base_command()
    return f'"{exe}" "{script}" "%1"'


def icon_path() -> str:
    launcher = get_launcher_path()
    return str(launcher) if launcher else AppProcess.base_command()[0]


def is_enabled(key: str = MENU_KEY) -> bool:
    if sys.platform != "win32":
        return False
    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CURRENT_USER, key))
    except FileNotFoundError:
        return False
    return True


def stored_command(key: str = MENU_KEY) -> str | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key + r"\command") as handle:
            return winreg.QueryValueEx(handle, "")[0]
    except FileNotFoundError:
        return None


def enable(command: str, key: str = MENU_KEY) -> None:
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as handle:
        winreg.SetValueEx(handle, "", 0, winreg.REG_SZ, MENU_LABEL)
        winreg.SetValueEx(handle, "Icon", 0, winreg.REG_SZ, icon_path())
        winreg.SetValueEx(handle, "MultiSelectModel", 0, winreg.REG_SZ, "Single")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key + r"\command") as handle:
        winreg.SetValueEx(handle, "", 0, winreg.REG_SZ, command)


def disable(key: str = MENU_KEY) -> None:
    if not is_enabled(key):
        return
    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key + r"\command")
    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)


def sync(key: str = MENU_KEY) -> None:
    if not is_enabled(key):
        return
    command = launch_command()
    if command and stored_command(key) != command:
        enable(command, key)
