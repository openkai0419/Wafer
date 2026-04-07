from __future__ import annotations

from PySide6 import QtGui

from ...utils.signal import Signal
from .theme_palette import DARK, LIGHT, ThemePalette


class ThemeManager:
    _instance: ThemeManager | None = None

    on_theme_changed = Signal()

    @classmethod
    def instance(cls) -> ThemeManager:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._palette: ThemePalette = ThemePalette.from_system()

    @property
    def palette(self) -> ThemePalette:
        return self._palette

    @property
    def is_dark(self) -> bool:
        c = QtGui.QColor(self._palette.bg_primary)
        return c.value() < 128

    def set_dark(self):
        self._apply(DARK)

    def set_light(self):
        self._apply(LIGHT)

    def toggle(self):
        self._apply(LIGHT if self.is_dark else DARK)

    def sync_system(self):
        self._apply(ThemePalette.from_system())

    def _apply(self, palette: ThemePalette):
        if self._palette == palette:
            return
        self._palette = palette
        self.on_theme_changed.emit(palette)
