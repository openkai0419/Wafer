from __future__ import annotations

from PySide6 import QtCore

from wafer.plugin import PluginConfig

DEFAULT_PALETTE_SLOTS = 6
MIN_PALETTE_SLOTS = 1
MAX_PALETTE_SLOTS = 30
APP_SETTINGS_KEY = "color/palette_slots"

color_config = PluginConfig(
    "color",
    {
        "palette_slots": DEFAULT_PALETTE_SLOTS,
    },
)


def normalize_palette_slots(value) -> int:
    try:
        slots = int(value)
    except (TypeError, ValueError):
        slots = DEFAULT_PALETTE_SLOTS
    return max(MIN_PALETTE_SLOTS, min(MAX_PALETTE_SLOTS, slots))


def plugin_palette_slots(settings: dict | None = None) -> int:
    source = settings if settings is not None else color_config.to_dict()
    return normalize_palette_slots(source.get("palette_slots", DEFAULT_PALETTE_SLOTS))


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
        from wafer.core.app_settings import app_settings

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


def palette_slots(settings: dict | None = None) -> int:
    if settings is not None:
        return plugin_palette_slots(settings)
    return ColorSettings.instance().palette_slots()


def palette_keys(slots: int | None = None) -> tuple[str, ...]:
    count = palette_slots({"palette_slots": slots}) if slots is not None else palette_slots()
    return tuple(f"palette.{i}" for i in range(1, count + 1))