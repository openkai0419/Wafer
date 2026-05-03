from __future__ import annotations
from typing import Any
from pathlib import Path
from PySide6 import QtWidgets
from .mouse.store import MouseBindingStore
from weakref import WeakSet
from PySide6 import QtCore
from .key.store import KeyBindingStore
from .key.sequence import KeySequence
from ....utils.logs import AppLogger
from .store_base import resolve_for_widget


class BindingManager:
    _instance: BindingManager | None = None

    def __init__(self, file_path: str | None = None, key_file_path: str | None = None):
        from .presets import get_mouse_preset_path, get_key_preset_path

        self._file = Path(file_path) if file_path else Path(get_mouse_preset_path())
        self._store = MouseBindingStore.instance()
        self._key_file = Path(key_file_path) if key_file_path else Path(get_key_preset_path())
        self._key_store = KeyBindingStore.instance()
        self._widgets: WeakSet[QtWidgets.QWidget] = WeakSet()

    @classmethod
    def instance(cls, file_path: str | None = None, key_file_path: str | None = None) -> BindingManager:
        if cls._instance is None:
            cls._instance = cls(file_path, key_file_path)
        else:
            if file_path:
                cls._instance._file = Path(file_path)
            if key_file_path:
                cls._instance._key_file = Path(key_file_path)
        return cls._instance

    @classmethod
    def configure(cls, mouse_bindings_path: str | Path, key_bindings_path: str | Path) -> BindingManager:
        return cls.instance(str(mouse_bindings_path), str(key_bindings_path))

    @classmethod
    def activate(cls, file_path: str | None = None, *, key_file_path: str | None = None):
        mgr = cls.instance(file_path, key_file_path)
        mgr._store.load_from_file(str(mgr._file))
        mgr._key_store.load_from_file(str(mgr._key_file))
        mgr.apply_registered()
        return mgr

    def apply_mouse_bindings(self, widgets: list[QtWidgets.QWidget]) -> None:
        data = self._store.get_all()
        for w in widgets:
            if not (hasattr(w, "binding_scope") and callable(w.binding_scope)):
                continue
            bindings = resolve_for_widget(data, w.binding_scope())
            if hasattr(w, "set_mouse_bindings"):
                w.set_mouse_bindings(bindings)

    def apply_key_bindings(self, widgets: list[QtWidgets.QWidget]) -> None:
        data = self._key_store.get_all()
        for w in widgets:
            if not (hasattr(w, "binding_scope") and callable(w.binding_scope)):
                continue
            resolved = resolve_for_widget(data, w.binding_scope())
            store_logical: dict[KeySequence, Any] = {}
            store_physical: dict[tuple[str | int, ...], Any] = {}
            for seq, cmd in resolved.items():
                if self._is_physical_seq(seq):
                    store_physical[seq.to_tuple()] = cmd
                else:
                    store_logical[seq] = cmd
            if store_logical and hasattr(w, "set_shortcut_bindings"):
                w.set_shortcut_bindings(store_logical)
            if store_physical and hasattr(w, "set_physical_shortcut_bindings"):
                w.set_physical_shortcut_bindings(store_physical)

    def apply_registered(self) -> None:
        ws = list(self._widgets)
        self.apply_mouse_bindings(ws)
        self.apply_key_bindings(ws)

    def clear_shortcuts(self, widgets: list[QtWidgets.QWidget]) -> None:
        for w in widgets:
            if hasattr(w, "set_shortcut_bindings"):
                w.set_shortcut_bindings({})

    def clear_shortcuts_registered(self) -> None:
        self.clear_shortcuts(list(self._widgets))

    def register(self, widget: QtWidgets.QWidget) -> None:
        try:
            self._widgets.add(widget)
            from .instance_registry import InstanceRegistry

            InstanceRegistry.instance().register_inferred(widget)
            self.apply_mouse_bindings([widget])
            self.apply_key_bindings([widget])
        except Exception as e:
            AppLogger.warning("BindingManager.register failed", exc=e)

    def save(self) -> None:
        self._store.save_to_file(str(self._file))
        self._key_store.save_to_file(str(self._key_file))

    def mouse_bindings_path(self) -> str:
        return str(self._file)

    def key_bindings_path(self) -> str:
        return str(self._key_file)

    def _find_registered_in_hierarchy(self, widget: QtWidgets.QWidget | None) -> QtWidgets.QWidget | None:
        cur = widget
        while cur is not None:
            try:
                if cur in self._widgets:
                    return cur
            except Exception as e:
                AppLogger.warning("BindingManager hierarchy lookup failed", exc=e)
            cur = cur.parentWidget()
        return None

    def find_binding_widget_at(self, global_pos: QtCore.QPoint) -> QtWidgets.QWidget | None:
        w = QtWidgets.QApplication.widgetAt(global_pos)
        return self._find_registered_in_hierarchy(w)

    def find_registered_ancestor(self, widget: QtWidgets.QWidget) -> QtWidgets.QWidget | None:
        return self._find_registered_in_hierarchy(widget)

    def _is_physical_seq(self, seq: KeySequence) -> bool:
        parts = seq.to_tuple()
        for part in parts:
            name = str(part).upper()
            if not name.startswith("SC") or not name[2:].isdigit():
                return False
        return bool(parts)
