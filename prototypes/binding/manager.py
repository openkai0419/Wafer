from __future__ import annotations
from typing import Dict, List, Optional, Any
from pathlib import Path
from PySide6 import QtWidgets
from .mouse.mouseeventmanager import MouseActionKey
from .mouse.store import MouseBindingStore
from weakref import WeakSet
from PySide6 import QtCore

class BindingManager:
    _instance: Optional["BindingManager"] = None

    def __init__(self, file_path: Optional[str] = None):
        if file_path:
            self._file = Path(file_path)
        else:
            self._file = Path(__file__).resolve().parent.parent / "mouse_bindings.json"
        self._store = MouseBindingStore()
        self._widgets: "WeakSet[QtWidgets.QWidget]" = WeakSet()

    @classmethod
    def instance(cls, file_path: Optional[str] = None) -> "BindingManager":
        if cls._instance is None:
            cls._instance = cls(file_path)
        return cls._instance
    
    @classmethod
    def activate(cls, file_path: Optional[str] =None, defaults: Optional[Dict[MouseActionKey, Any]]=None):
        mgr = cls.instance(file_path)
        mgr.load_or_seed(defaults)
        mgr.apply_registered()
        mgr.clear_shortcuts_registered()
        return mgr
    
    def load_or_seed(self, defaults: Dict[MouseActionKey, Any]) -> Dict[MouseActionKey, Dict[str, Any]]:
        loaded = self._store.load_from_file(str(self._file))
        if not loaded:
            initial: Dict[MouseActionKey, Dict[str, Any]] = {}
            for k, v in defaults.items():
                initial[k] = {"*": v}
            self._store.set_all(initial)
        return self._store.get_all()
    
    def apply_mouse_bindings(self, widgets: List[QtWidgets.QWidget]) -> None:
        data = self._store.get_all()
        for w in widgets:
            name = self._scope_of(w)
            applied: Dict[MouseActionKey, Any] = {}
            for key, scopes in data.items():
                cmd = scopes.get(name) or scopes.get("*")
                if cmd:
                    applied[key] = cmd
            if hasattr(w, "set_mouse_bindings"):
                w.set_mouse_bindings(applied)

    def apply_registered(self) -> None:
        self.apply_mouse_bindings(list(self._widgets))

    def clear_shortcuts(self, widgets: List[QtWidgets.QWidget]) -> None:
        for w in widgets:
            if hasattr(w, "set_shortcut_bindings"):
                w.set_shortcut_bindings({})

    def clear_shortcuts_registered(self) -> None:
        self.clear_shortcuts(list(self._widgets))

    def register(self, widget: QtWidgets.QWidget) -> None:
        try:
            self._widgets.add(widget)
        except Exception:
            pass

    def save(self) -> None:
        self._store.save_to_file(str(self._file))

    def _scope_of(self, widget: QtWidgets.QWidget) -> str:
        if hasattr(widget, "binding_scope") and callable(getattr(widget, "binding_scope")):
            return widget.binding_scope()
        raise ValueError(f"Widget {widget} does not implement binding_scope()")

    def find_binding_widget_at(self, global_pos: QtCore.QPoint) -> Optional[QtWidgets.QWidget]:
        w = QtWidgets.QApplication.widgetAt(global_pos)
        if not w:
            return None
        cur = w
        while cur is not None:
            try:
                if cur in self._widgets:
                    return cur
            except Exception:
                pass
            cur = cur.parentWidget()
        return None