import sys
from pathlib import Path

from ..common.paths import get_launcher_path
from .process import MAIN_SCRIPT, AppProcess

if sys.platform == "win32":
    import winreg

MENU_KEY = r"Software\Classes\*\shell\Wafer"
MENU_LABEL = "Open with Wafer"


def dev_interpreter() -> str:
    if not AppProcess._in_venv():
        return AppProcess.base_command()[0]
    windowless = Path(sys.executable).with_name("pythonw.exe")
    return str(windowless if windowless.is_file() else sys.executable)


def launch_command() -> str | None:
    if sys.platform != "win32":
        return None
    launcher = get_launcher_path()
    if launcher:
        return f'"{launcher}" "%1"'
    return f'"{dev_interpreter()}" "{MAIN_SCRIPT}" "%1"'


def icon_path() -> str:
    launcher = get_launcher_path()
    return str(launcher) if launcher else dev_interpreter()


def key_exists(key: str) -> bool:
    if sys.platform != "win32":
        return False
    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CURRENT_USER, key))
    except FileNotFoundError:
        return False
    return True


def is_enabled(key: str = MENU_KEY) -> bool:
    return key_exists(key)


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


def delete_key_tree(key: str) -> None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as handle:
        children = [winreg.EnumKey(handle, i) for i in range(winreg.QueryInfoKey(handle)[0])]
    for child in children:
        delete_key_tree(key + "\\" + child)
    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)


def disable(key: str = MENU_KEY) -> None:
    if is_enabled(key):
        delete_key_tree(key)


def sync(key: str = MENU_KEY) -> None:
    if not is_enabled(key):
        return
    command = launch_command()
    if command and stored_command(key) != command:
        enable(command, key)
