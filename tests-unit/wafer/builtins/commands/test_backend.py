import pytest
from PySide6 import QtWidgets

from wafer.app.webui.settings import HOST_ALL, WebUISettings
from wafer.builtins.commands import backend


class NoWindowCtx:
    def get_instance(self, name):
        return None


@pytest.fixture
def settings_path(tmp_path, monkeypatch):
    path = str(tmp_path / "webui_settings.ini")
    monkeypatch.setattr("wafer.app.webui.settings._path", lambda: path)
    return path


def run_dialog(monkeypatch, edit):
    shown = {}

    def fake_exec(dialog):
        shown["hosts"] = dialog.findChild(QtWidgets.QLineEdit).text()
        edit(dialog)
        save = next(b for b in dialog.findChildren(QtWidgets.QPushButton) if b.text() == "Save")
        save.click()
        return dialog.result()

    monkeypatch.setattr(QtWidgets.QDialog, "exec", fake_exec)
    backend.open_settings(NoWindowCtx())
    return shown


def test_settings_dialog_saves_allowed_hosts(qtbot, settings_path, monkeypatch):
    def edit(dialog):
        dialog.findChild(QtWidgets.QComboBox).setCurrentIndex(1)
        dialog.findChild(QtWidgets.QLineEdit).setText("NAS.example.com, *.home.example.net, bad_host!")

    run_dialog(monkeypatch, edit)
    settings = WebUISettings()
    assert settings.host() == HOST_ALL
    assert settings.allowed_hosts() == ("nas.example.com", "*.home.example.net")


def test_settings_dialog_shows_saved_allowed_hosts(qtbot, settings_path, monkeypatch):
    WebUISettings().save(HOST_ALL, 8787, ("nas.example.com",))
    shown = run_dialog(monkeypatch, lambda dialog: None)
    assert shown["hosts"] == "nas.example.com"
    assert WebUISettings().allowed_hosts() == ("nas.example.com",)
