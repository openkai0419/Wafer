from __future__ import annotations
from typing import Dict, List, Optional, Any, Tuple, Union
from pathlib import Path
from PySide6 import QtWidgets
from source.common.profiling import profiler
from .mouse.mouseeventmanager import MouseActionKey
from .mouse.store import MouseBindingStore
from weakref import WeakSet
from PySide6 import QtCore
from .key.store import KeyBindingStore
from .key.sequence import KeySequence

class BindingManager:
    _instance: Optional["BindingManager"] = None

    def __init__(self, file_path: Optional[str] = None):
        if file_path:
            self._file = Path(file_path)
        else:
            self._file = Path(__file__).resolve().parent.parent / "mouse_bindings.json"
        self._store = MouseBindingStore()
        self._key_file = Path(__file__).resolve().parent.parent / "key_bindings.json"
        self._key_store = KeyBindingStore()
        self._key_defaults: List[Tuple[Tuple[Union[str,int], ...], Any]] = []
        self._widgets: "WeakSet[QtWidgets.QWidget]" = WeakSet()

    @classmethod
    def instance(cls, file_path: Optional[str] = None) -> "BindingManager":
        if cls._instance is None:
            cls._instance = cls(file_path)
        return cls._instance
    
    @classmethod
    def activate(cls, file_path: Optional[str] = None, defaults: Optional[Dict[MouseActionKey, Any]] = None, key_defaults: Optional[List[Tuple[Tuple[Union[str,int], ...], Any]]] = None):
        mgr = cls.instance(file_path)
        mgr.load_or_seed(defaults)
        if key_defaults is not None:
            mgr.set_key_defaults(key_defaults)
            mgr.load_or_seed_keys()
        mgr.apply_registered()
        return mgr
    
    @profiler.profile
    def load_or_seed(self, defaults: Dict[MouseActionKey, Any]) -> Dict[MouseActionKey, Dict[str, Any]]:
        loaded = self._store.load_from_file(str(self._file))
        if not loaded:
            initial: Dict[MouseActionKey, Dict[str, Any]] = {}
            for k, v in defaults.items():
                initial[k] = {"*": v}
            self._store.set_all(initial)
        return self._store.get_all()

    def load_or_seed_keys(self):
        from pathlib import Path
        key_path = Path(__file__).resolve().parent.parent / "key_bindings.json"
        loaded = self._key_store.load_from_file(str(key_path))
        if loaded:
            return
        if not self._key_defaults:
            return
        data: Dict[KeySequence, Dict[str, Any]] = {}
        for spec, payload in self._key_defaults:
            seq = KeySequence(spec)
            data[seq] = {"*": payload}
        self._key_store.set_all(data)

    def set_key_defaults(self, defaults: List[Tuple[Tuple[Union[str,int], ...], Any]]):
        self._key_defaults = []
        for spec, payload in list(defaults or []):
            if not isinstance(spec, (tuple, list)):
                continue
            tup = tuple(spec)
            if not tup:
                continue
            self._key_defaults.append((tup, payload))
    
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

    def apply_key_bindings(self, widgets: List[QtWidgets.QWidget]) -> None:
        data = self._key_store.get_all()
        base_logical: Dict[Tuple[Union[str,int], ...], Any] = {}
        base_physical: Dict[Tuple[Union[str,int], ...], Any] = {}
        for spec, payload in list(self._key_defaults or []):
            if self._is_physical_spec(spec):
                base_physical[spec] = payload
            else:
                base_logical[spec] = payload
        for w in widgets:
            name = self._scope_of(w)
            store_logical: Dict[str, Any] = {}
            store_physical: Dict[str, Any] = {}
            for seq, scopes in data.items():
                cmd = scopes.get(name) or scopes.get("*")
                if not cmd:
                    continue
                if self._is_physical_seq(seq):
                    store_physical[seq] = cmd
                else:
                    store_logical[seq] = cmd
            if base_logical and hasattr(w, "set_key_bindings"):
                w.set_key_bindings(base_logical)
            if base_physical and hasattr(w, "set_physical_shortcut_bindings"):
                w.set_physical_shortcut_bindings(base_physical)
            if store_logical and hasattr(w, "set_shortcut_bindings"):
                w.set_shortcut_bindings(store_logical)
            if store_physical and hasattr(w, "set_physical_shortcut_bindings"):
                w.set_physical_shortcut_bindings(store_physical)

    def apply_registered(self) -> None:
        ws = list(self._widgets)
        self.apply_mouse_bindings(ws)
        self.apply_key_bindings(ws)

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
        try:
            self._key_store.save_to_file(str(self._key_file))
        except Exception:
            pass

    def _scope_of(self, widget: QtWidgets.QWidget) -> str:
        if hasattr(widget, "binding_scope") and callable(getattr(widget, "binding_scope")):
            return widget.binding_scope()
        raise ValueError(f"Widget {widget} does not implement binding_scope()")

    def _find_registered_in_hierarchy(self, widget: Optional[QtWidgets.QWidget]) -> Optional[QtWidgets.QWidget]:
        cur = widget
        while cur is not None:
            try:
                if cur in self._widgets:
                    return cur
            except Exception:
                pass
            cur = cur.parentWidget()
        return None

    def find_binding_widget_at(self, global_pos: QtCore.QPoint) -> Optional[QtWidgets.QWidget]:
        w = QtWidgets.QApplication.widgetAt(global_pos)
        return self._find_registered_in_hierarchy(w)

    def find_registered_ancestor(self, widget: QtWidgets.QWidget) -> Optional[QtWidgets.QWidget]:
        return self._find_registered_in_hierarchy(widget)

    def _is_physical_seq(self, seq: KeySequence) -> bool:
        parts = seq.to_tuple()
        for p in parts:
            u = str(p).upper()
            if u.startswith("SC"):
                try:
                    int(u[2:])
                    continue
                except Exception:
                    return False
            else:
                try:
                    int(u)
                except Exception:
                    return False
        return True

    def _is_physical_spec(self, spec: Tuple[Union[str,int], ...]) -> bool:
        for t in spec:
            if isinstance(t, int):
                return True
            if isinstance(t, str) and t.strip().upper().startswith("SC"):
                return True
        return False