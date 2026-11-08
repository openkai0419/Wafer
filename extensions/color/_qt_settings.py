from __future__ import annotations

from PySide6 import QtCore

from .settings import (
    APP_SETTINGS_KEY,
    color_config,
    normalize_palette_slots,
    palette_keys,
    plugin_palette_slots,
)


class ColorSettings(QtCore.QObject):
    changed = QtCore.Signal()

    _instance: ColorSettings | None = None

    def __init__(self, parent: QtCore.QObject | None = None):
        super().__init__(parent)
        self._palette_slots = self._load_palette_slots()
        self._app_settings().key_changed.connect(self._on_setting_changed)

    @classmethod
    def instance(cls) -> ColorSettings:
        if cls._instance is None:
            cls._instance = ColorSettings()
        return cls._instance

    @staticmethod
    def _app_settings():
        from wafer.core.store.settings import app_settings

        return app_settings

    def _load_palette_slots(self) -> int:
        return normalize_palette_slots(self._app_settings().get(APP_SETTINGS_KEY, plugin_palette_slots(), int))

    def palette_slots(self) -> int:
        return self._palette_slots

    def palette_keys(self) -> tuple[str, ...]:
        return palette_keys(self._palette_slots)

    def save_palette_slots(self, value: int) -> int:
        slots = normalize_palette_slots(value)
        self._app_settings().set(APP_SETTINGS_KEY, slots)
        self._app_settings().commit()
        color_config.save_and_notify("color", palette_slots=slots)
        self._set_palette_slots(slots)
        return slots

    @QtCore.Slot(str)
    def _on_setting_changed(self, key: str):
        if key != APP_SETTINGS_KEY:
            return
        self.reload()

    def reload(self):
        self._set_palette_slots(self._load_palette_slots())

    def _set_palette_slots(self, slots: int):
        slots = normalize_palette_slots(slots)
        if self._palette_slots == slots:
            return
        self._palette_slots = slots
        self.changed.emit()
