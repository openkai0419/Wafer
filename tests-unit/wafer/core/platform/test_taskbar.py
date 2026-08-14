import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from wafer.constants import APP_ID, APP_NAME
from wafer.core.platform import taskbar


def test_no_op_when_launcher_missing(monkeypatch):
    monkeypatch.setattr(taskbar, "get_launcher_path", lambda: None)
    taskbar.apply_window_identity(12345)


def test_no_op_on_zero_hwnd(monkeypatch):
    monkeypatch.setattr(taskbar, "get_launcher_path", lambda: Path("nonexistent.exe"))
    taskbar.apply_window_identity(0)


@pytest.mark.skipif(sys.platform != "win32", reason="taskbar identity is win32-only")
def test_sets_relaunch_properties(monkeypatch, tmp_path):
    from win32com import propsys as propsys_package

    class PropertyStore:
        def __init__(self):
            self.values = {}
            self.committed = False

        def SetValue(self, key, value):
            self.values[key] = value

        def Commit(self):
            self.committed = True

    launcher = tmp_path / f"{APP_NAME}.exe"
    launcher.write_bytes(b"MZ")
    store = PropertyStore()
    app_id_key = object()
    command_key = object()
    display_name_key = object()
    icon_key = object()
    value_type = object()
    propsys = SimpleNamespace(
        IID_IPropertyStore=object(),
        SHGetPropertyStoreForWindow=lambda hwnd, iid: store,
        PROPVARIANTType=lambda value, variant_type: (value, variant_type),
    )
    pscon = SimpleNamespace(
        PKEY_AppUserModel_ID=app_id_key,
        PKEY_AppUserModel_RelaunchCommand=command_key,
        PKEY_AppUserModel_RelaunchDisplayNameResource=display_name_key,
        PKEY_AppUserModel_RelaunchIconResource=icon_key,
    )
    monkeypatch.setattr(taskbar, "get_launcher_path", lambda: launcher)
    monkeypatch.setitem(sys.modules, "pythoncom", SimpleNamespace(VT_LPWSTR=value_type))
    monkeypatch.setattr(propsys_package, "propsys", propsys, raising=False)
    monkeypatch.setattr(propsys_package, "pscon", pscon, raising=False)

    taskbar.apply_window_identity(12345)

    launcher_path = str(launcher)
    assert store.values == {
        app_id_key: (APP_ID, value_type),
        command_key: (f'"{launcher_path}"', value_type),
        display_name_key: (APP_NAME, value_type),
        icon_key: (f'"{launcher_path}",0', value_type),
    }
    assert store.committed
