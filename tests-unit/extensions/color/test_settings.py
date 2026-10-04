from __future__ import annotations

from unittest.mock import MagicMock

from PySide6 import QtCore

from extensions.color.settings import APP_SETTINGS_KEY, ColorSettings


class _FakeAppSettings(QtCore.QObject):
    key_changed = QtCore.Signal(str)

    def __init__(self, initial=None):
        super().__init__()
        self.values = dict(initial or {})
        self.commits = 0

    def get(self, key, default=None, value_type=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value

    def commit(self):
        self.commits += 1


def test_color_settings_save_updates_app_settings_and_notifies_collector(qapp, monkeypatch):
    fake_app = _FakeAppSettings({APP_SETTINGS_KEY: 6})
    save_and_notify = MagicMock()
    monkeypatch.setattr(ColorSettings, "_instance", None)
    monkeypatch.setattr(ColorSettings, "_app_settings", staticmethod(lambda: fake_app))
    monkeypatch.setattr("extensions.color.settings.color_config.save_and_notify", save_and_notify)

    settings = ColorSettings.instance()
    changed = MagicMock()
    settings.changed.connect(changed)

    assert settings.save_palette_slots(8) == 8
    assert settings.palette_slots() == 8
    assert fake_app.values[APP_SETTINGS_KEY] == 8
    assert fake_app.commits == 1
    save_and_notify.assert_called_once_with("color", palette_slots=8)
    changed.assert_called_once()


def test_color_settings_reloads_on_remote_app_settings_change(qapp, monkeypatch):
    fake_app = _FakeAppSettings({APP_SETTINGS_KEY: 6})
    monkeypatch.setattr(ColorSettings, "_instance", None)
    monkeypatch.setattr(ColorSettings, "_app_settings", staticmethod(lambda: fake_app))

    settings = ColorSettings.instance()
    changed = MagicMock()
    settings.changed.connect(changed)
    fake_app.values[APP_SETTINGS_KEY] = 9
    fake_app.key_changed.emit(APP_SETTINGS_KEY)

    assert settings.palette_slots() == 9
    changed.assert_called_once()
