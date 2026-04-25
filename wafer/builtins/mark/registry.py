from __future__ import annotations

from PySide6 import QtCore, QtGui

from ...core.app_settings import app_settings


_SETTINGS_KEY = "marks/colors"
_TAG_PREFIX = "mark"

_DEFAULT_COLORS: dict[str, str] = {
    "1": "#E53935",
    "2": "#FB8C00",
    "3": "#FDD835",
    "4": "#43A047",
    "5": "#1E88E5",
    "6": "#8E24AA",
    "7": "#EC407A",
    "8": "#9E9E9E",
    "9": "#FAFAFA",
}


class MarkRegistry(QtCore.QObject):
    changed = QtCore.Signal()

    _instance: MarkRegistry | None = None

    def __init__(self, parent: QtCore.QObject | None = None):
        super().__init__(parent)
        self._colors: dict[str, str] = self._load()

    @classmethod
    def instance(cls) -> MarkRegistry:
        if cls._instance is None:
            cls._instance = MarkRegistry()
        return cls._instance

    def _load(self) -> dict[str, str]:
        saved = app_settings.get(_SETTINGS_KEY, None, dict)
        if isinstance(saved, dict) and saved:
            return {str(k): str(v) for k, v in saved.items()}
        return dict(_DEFAULT_COLORS)

    def _save(self):
        app_settings.set(_SETTINGS_KEY, dict(self._colors))
        app_settings.commit()

    def colors(self) -> dict[str, str]:
        return dict(self._colors)

    def ids(self) -> list[str]:
        return sorted(self._colors.keys(), key=lambda x: (len(x), x))

    def color_for(self, mark_id: str) -> str:
        return self._colors.get(str(mark_id), "#888888")

    def qcolor_for(self, mark_id: str) -> QtGui.QColor:
        return QtGui.QColor(self.color_for(mark_id))

    def set_color(self, mark_id: str, hex_color: str):
        mark_id = str(mark_id)
        hex_color = str(hex_color)
        if self._colors.get(mark_id) == hex_color:
            return
        self._colors[mark_id] = hex_color
        self._save()
        self.changed.emit()

    def add_id(self, mark_id: str, hex_color: str | None = None):
        mark_id = str(mark_id)
        if mark_id in self._colors:
            return
        self._colors[mark_id] = hex_color or "#888888"
        self._save()
        self.changed.emit()

    def remove_id(self, mark_id: str):
        mark_id = str(mark_id)
        if mark_id not in self._colors:
            return
        del self._colors[mark_id]
        self._save()
        self.changed.emit()

    @staticmethod
    def tag_key(mark_id: str) -> str:
        return f"{_TAG_PREFIX}.{mark_id}"

    @staticmethod
    def parse_key(key: str) -> str | None:
        if not key or not key.startswith(_TAG_PREFIX + "."):
            return None
        rest = key[len(_TAG_PREFIX) + 1 :]
        return rest or None

    @staticmethod
    def tag_prefix() -> str:
        return _TAG_PREFIX
