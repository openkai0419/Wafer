import sys
from pathlib import Path

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
    from PySide6 import QtWidgets
    from win32com.propsys import propsys, pscon

    launcher = tmp_path / f"{APP_NAME}.exe"
    launcher.write_bytes(b"MZ")
    monkeypatch.setattr(taskbar, "get_launcher_path", lambda: launcher)

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    widget = QtWidgets.QWidget()
    widget.show()
    hwnd = int(widget.winId())
    try:
        taskbar.apply_window_identity(hwnd)
        store = propsys.SHGetPropertyStoreForWindow(hwnd, propsys.IID_IPropertyStore)
        assert store.GetValue(pscon.PKEY_AppUserModel_ID).GetValue() == APP_ID
        assert store.GetValue(pscon.PKEY_AppUserModel_RelaunchDisplayNameResource).GetValue() == APP_NAME
        relaunch_cmd = store.GetValue(pscon.PKEY_AppUserModel_RelaunchCommand).GetValue()
        assert str(launcher) in relaunch_cmd
        relaunch_icon = store.GetValue(pscon.PKEY_AppUserModel_RelaunchIconResource).GetValue()
        assert str(launcher) in relaunch_icon
    finally:
        widget.deleteLater()
        app.processEvents()
