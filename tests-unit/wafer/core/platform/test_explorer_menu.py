import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows registry only")

TEST_ROOT = r"Software\WaferTest"
TEST_KEY = TEST_ROOT + r"\shell\Wafer"


def read_value(sub_key, name=""):
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub_key) as handle:
        return winreg.QueryValueEx(handle, name)[0]


def delete_tree(sub_key):
    import winreg

    try:
        handle = winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub_key, 0, winreg.KEY_ALL_ACCESS)
    except FileNotFoundError:
        return
    with handle:
        while True:
            try:
                child = winreg.EnumKey(handle, 0)
            except OSError:
                break
            delete_tree(sub_key + "\\" + child)
    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub_key)


@pytest.fixture
def test_key():
    delete_tree(TEST_ROOT)
    yield TEST_KEY
    delete_tree(TEST_ROOT)


def test_enable_then_disable_roundtrip(test_key):
    from wafer.core.platform import explorer_menu

    assert not explorer_menu.is_enabled(test_key)
    explorer_menu.enable('"C:\\Wafer\\Wafer.exe" "%1"', test_key)
    assert explorer_menu.is_enabled(test_key)
    assert read_value(test_key + r"\command") == '"C:\\Wafer\\Wafer.exe" "%1"'
    assert read_value(test_key) == "Open with Wafer"
    assert read_value(test_key, "MultiSelectModel") == "Single"
    assert read_value(test_key, "Icon")
    explorer_menu.disable(test_key)
    assert not explorer_menu.is_enabled(test_key)


def test_disable_missing_key_is_noop(test_key):
    from wafer.core.platform import explorer_menu

    explorer_menu.disable(test_key)
    assert not explorer_menu.is_enabled(test_key)


def test_disable_removes_key_without_command_subkey(test_key):
    import winreg

    from wafer.core.platform import explorer_menu

    winreg.CloseKey(winreg.CreateKey(winreg.HKEY_CURRENT_USER, test_key))
    assert explorer_menu.is_enabled(test_key)
    explorer_menu.disable(test_key)
    assert not explorer_menu.is_enabled(test_key)


def test_sync_rewrites_moved_command(test_key, monkeypatch):
    from wafer.core.platform import explorer_menu

    explorer_menu.enable("old", test_key)
    monkeypatch.setattr(explorer_menu, "launch_command", lambda: "new")
    explorer_menu.sync(test_key)
    assert read_value(test_key + r"\command") == "new"
    assert read_value(test_key, "MultiSelectModel") == "Single"


def test_sync_leaves_disabled_alone(test_key, monkeypatch):
    from wafer.core.platform import explorer_menu

    monkeypatch.setattr(explorer_menu, "launch_command", lambda: "new")
    explorer_menu.sync(test_key)
    assert not explorer_menu.is_enabled(test_key)


def test_launch_command_prefers_launcher(monkeypatch):
    from wafer.core.platform import explorer_menu

    launcher = Path("C:/Wafer/Wafer.exe")
    monkeypatch.setattr(explorer_menu, "get_launcher_path", lambda: launcher)
    assert explorer_menu.launch_command() == f'"{launcher}" "%1"'


def test_launch_command_outside_venv_uses_base_command(monkeypatch):
    from wafer.core.platform import explorer_menu
    from wafer.core.platform.process import AppProcess

    monkeypatch.setattr(explorer_menu, "get_launcher_path", lambda: None)
    monkeypatch.setattr(AppProcess, "_in_venv", staticmethod(lambda: False))
    exe, script = AppProcess.base_command()
    assert explorer_menu.launch_command() == f'"{exe}" "{script}" "%1"'


def test_launch_command_in_venv_uses_venv_pythonw(monkeypatch, tmp_path):
    from wafer.core.platform import explorer_menu
    from wafer.core.platform.process import MAIN_SCRIPT, AppProcess

    python = tmp_path / "python.exe"
    pythonw = tmp_path / "pythonw.exe"
    python.touch()
    pythonw.touch()
    monkeypatch.setattr(explorer_menu, "get_launcher_path", lambda: None)
    monkeypatch.setattr(AppProcess, "_in_venv", staticmethod(lambda: True))
    monkeypatch.setattr(sys, "executable", str(python))
    assert explorer_menu.launch_command() == f'"{pythonw}" "{MAIN_SCRIPT}" "%1"'
    assert explorer_menu.icon_path() == str(pythonw)


def test_launch_command_in_venv_without_pythonw_uses_python(monkeypatch, tmp_path):
    from wafer.core.platform import explorer_menu
    from wafer.core.platform.process import MAIN_SCRIPT, AppProcess

    python = tmp_path / "python.exe"
    python.touch()
    monkeypatch.setattr(explorer_menu, "get_launcher_path", lambda: None)
    monkeypatch.setattr(AppProcess, "_in_venv", staticmethod(lambda: True))
    monkeypatch.setattr(sys, "executable", str(python))
    assert explorer_menu.launch_command() == f'"{python}" "{MAIN_SCRIPT}" "%1"'


def test_toggle_command_follows_registry(test_key, monkeypatch):
    from wafer.builtins.commands.setting import SettingCommands
    from wafer.core.platform import explorer_menu

    original = (explorer_menu.is_enabled, explorer_menu.enable, explorer_menu.disable)
    monkeypatch.setattr(explorer_menu, "is_enabled", lambda key=test_key: original[0](key))
    monkeypatch.setattr(explorer_menu, "enable", lambda command, key=test_key: original[1](command, key))
    monkeypatch.setattr(explorer_menu, "disable", lambda key=test_key: original[2](key))
    monkeypatch.setattr(explorer_menu, "launch_command", lambda: "cmd")
    command = next(item for item in SettingCommands.commands() if getattr(item, "path", "") == "setting.explorer_menu")
    assert command.display == "Explorer Menu"
    assert not command.hidden
    assert command.checked() is False
    command.func(None)
    assert command.checked() is True
    assert read_value(test_key + r"\command") == "cmd"
    command.func(None)
    assert command.checked() is False
