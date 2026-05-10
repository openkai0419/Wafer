from __future__ import annotations

import re
from dataclasses import dataclass

from PySide6 import QtCore, QtGui

from ...core.app_settings import app_settings
from ...core.db.key_value import SCOPE_META_INFO, SCOPE_TAG, normalize_data_scope
from ...core.qt.badge_engine import badge_shape_pixmap, normalize_badge_shape_key
from ...utils.logs import AppLogger
from .shapes import DEFAULT_SHAPE_KEY


_SETTINGS_KEY = "marks/items"
_TAG_PREFIX = "mark"

_ID_PATTERN = re.compile(r"[^a-z0-9]+")


def _normalize_name(text: str) -> str:
    return str(text or "").strip().lower()


@dataclass(frozen=True)
class Mark:
    id: str
    name: str
    color: str
    storage_scope: str = SCOPE_META_INFO
    shape_key: str = DEFAULT_SHAPE_KEY


def _normalize_id(text: str) -> str:
    base = _ID_PATTERN.sub("_", str(text or "").strip().lower()).strip("_")
    return base or "mark"


def _normalize_storage_scope(scope: str) -> str:
    try:
        normalized = normalize_data_scope(scope)
    except ValueError:
        return SCOPE_META_INFO
    if normalized in (SCOPE_META_INFO, SCOPE_TAG):
        return normalized
    return SCOPE_META_INFO


def _coerce_shape_key(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return DEFAULT_SHAPE_KEY
    return normalize_badge_shape_key(text)


class MarkRegistry(QtCore.QObject):
    changed = QtCore.Signal()

    _instance: MarkRegistry | None = None

    def __init__(self, parent: QtCore.QObject | None = None):
        super().__init__(parent)
        self._marks: list[Mark] = self._load()
        app_settings.key_changed.connect(self._on_setting_changed)

    @QtCore.Slot(str)
    def _on_setting_changed(self, key: str):
        if key != _SETTINGS_KEY:
            return
        self._marks = self._load()
        self.changed.emit()

    @classmethod
    def instance(cls) -> MarkRegistry:
        if cls._instance is None:
            cls._instance = MarkRegistry()
        return cls._instance

    def _load(self) -> list[Mark]:
        saved = app_settings.get(_SETTINGS_KEY, None, list)
        if isinstance(saved, list) and saved:
            out: list[Mark] = []
            seen_ids: set[str] = set()
            seen_names: set[str] = set()
            duplicates_renamed = 0
            for item in saved:
                if not isinstance(item, dict):
                    continue
                mark_id = str(item.get("id") or "").strip()
                if not mark_id or mark_id in seen_ids:
                    continue
                name = str(item.get("name") or mark_id)
                color = str(item.get("color") or "#888888")
                shape_key = _coerce_shape_key(item.get("shape_key") or item.get("mark_key"))
                storage_scope = _normalize_storage_scope(item.get("storage_scope") or SCOPE_META_INFO)
                norm = _normalize_name(name)
                if norm in seen_names:
                    base = name
                    i = 2
                    while _normalize_name(f"{base} {i}") in seen_names:
                        i += 1
                    name = f"{base} {i}"
                    norm = _normalize_name(name)
                    duplicates_renamed += 1
                seen_ids.add(mark_id)
                seen_names.add(norm)
                out.append(Mark(id=mark_id, name=name, color=color, storage_scope=storage_scope, shape_key=shape_key))
            if duplicates_renamed:
                AppLogger.warning(f"[Mark] Renamed {duplicates_renamed} duplicate mark name(s) on load")
            if out:
                return out
        return [Mark(id="1", name="mark", color="#888888", storage_scope=SCOPE_META_INFO, shape_key=DEFAULT_SHAPE_KEY)]

    def _save(self):
        payload = [{"id": m.id, "name": m.name, "color": m.color, "storage_scope": m.storage_scope, "shape_key": m.shape_key} for m in self._marks]
        app_settings.set(_SETTINGS_KEY, payload)
        app_settings.commit()

    def marks(self) -> list[Mark]:
        return list(self._marks)

    def ids(self) -> list[str]:
        return [m.id for m in self._marks]

    def get(self, mark_id: str) -> Mark | None:
        mark_id = str(mark_id)
        for m in self._marks:
            if m.id == mark_id:
                return m
        return None

    def name_of(self, mark_id: str) -> str:
        m = self.get(mark_id)
        return m.name if m else str(mark_id)

    def color_of(self, mark_id: str) -> str:
        m = self.get(mark_id)
        return m.color if m else "#888888"

    def qcolor_of(self, mark_id: str) -> QtGui.QColor:
        return QtGui.QColor(self.color_of(mark_id))

    def shape_key_of(self, mark_id: str) -> str:
        m = self.get(mark_id)
        return m.shape_key if m else DEFAULT_SHAPE_KEY

    def scope_of(self, mark_id: str) -> str:
        m = self.get(mark_id)
        return m.storage_scope if m is not None else SCOPE_META_INFO

    def set_scope(self, mark_id: str, scope: str) -> bool:
        m = self.get(mark_id)
        scope = _normalize_storage_scope(scope)
        if m is None or m.storage_scope == scope:
            return False
        idx = self._marks.index(m)
        self._marks[idx] = Mark(id=m.id, name=m.name, color=m.color, storage_scope=scope, shape_key=m.shape_key)
        self._save()
        self.changed.emit()
        return True

    def ids_by_scope(self, scope: str) -> list[str]:
        scope = _normalize_storage_scope(scope)
        return [m.id for m in self._marks if m.storage_scope == scope]

    def swatch_icon(self, mark_id: str, size: int) -> QtGui.QIcon:
        size = max(1, int(size))
        pm = badge_shape_pixmap(self.shape_key_of(mark_id), size, self.qcolor_of(mark_id))
        return QtGui.QIcon(pm)

    def _unique_id(self, base: str) -> str:
        existing = {m.id for m in self._marks}
        if base not in existing:
            return base
        i = 2
        while f"{base}_{i}" in existing:
            i += 1
        return f"{base}_{i}"

    def _name_taken(self, name: str, exclude_id: str | None = None) -> bool:
        norm = _normalize_name(name)
        return any(_normalize_name(m.name) == norm and m.id != exclude_id for m in self._marks)

    def _unique_name(self, base: str, exclude_id: str | None = None) -> str:
        if not self._name_taken(base, exclude_id):
            return base
        i = 2
        while self._name_taken(f"{base} {i}", exclude_id):
            i += 1
        return f"{base} {i}"

    def add(self, name: str, color: str = "#888888", mark_id: str | None = None, *, storage_scope: str = SCOPE_META_INFO, shape_key: str = DEFAULT_SHAPE_KEY) -> str:
        display = str(name).strip()
        if not display:
            raise ValueError("Mark name must not be empty")
        display = self._unique_name(display)
        new_id = self._unique_id(mark_id or _normalize_id(display))
        self._marks.append(Mark(id=new_id, name=display, color=str(color), storage_scope=_normalize_storage_scope(storage_scope), shape_key=_coerce_shape_key(shape_key)))
        self._save()
        self.changed.emit()
        return new_id

    def remove(self, mark_id: str):
        mark_id = str(mark_id)
        before = len(self._marks)
        self._marks = [m for m in self._marks if m.id != mark_id]
        if len(self._marks) != before:
            self._save()
            self.changed.emit()

    def rename(self, mark_id: str, name: str) -> str | None:
        m = self.get(mark_id)
        if m is None:
            return None
        new_name = str(name).strip()
        if not new_name:
            raise ValueError("Mark name must not be empty")
        new_name = self._unique_name(new_name, exclude_id=mark_id)
        if m.name == new_name:
            return new_name
        idx = self._marks.index(m)
        self._marks[idx] = Mark(id=m.id, name=new_name, color=m.color, storage_scope=m.storage_scope, shape_key=m.shape_key)
        self._save()
        self.changed.emit()
        return new_name

    def set_color(self, mark_id: str, hex_color: str):
        m = self.get(mark_id)
        hex_color = str(hex_color)
        if m is None or m.color == hex_color:
            return
        idx = self._marks.index(m)
        self._marks[idx] = Mark(id=m.id, name=m.name, color=hex_color, storage_scope=m.storage_scope, shape_key=m.shape_key)
        self._save()
        self.changed.emit()

    def set_shape_key(self, mark_id: str, shape_key: str):
        m = self.get(mark_id)
        shape_key = _coerce_shape_key(shape_key)
        if m is None or m.shape_key == shape_key:
            return
        idx = self._marks.index(m)
        self._marks[idx] = Mark(id=m.id, name=m.name, color=m.color, storage_scope=m.storage_scope, shape_key=shape_key)
        self._save()
        self.changed.emit()

    def move(self, mark_id: str, index: int):
        mark_id = str(mark_id)
        for i, m in enumerate(self._marks):
            if m.id == mark_id:
                if i == index:
                    return
                self._marks.insert(max(0, min(index, len(self._marks) - 1)), self._marks.pop(i))
                self._save()
                self.changed.emit()
                return

    @staticmethod
    def key(mark_id: str) -> str:
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
