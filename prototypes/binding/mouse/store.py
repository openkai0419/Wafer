from __future__ import annotations
from typing import Any, Dict, Optional, List
from pathlib import Path
from ...utils import read_json_file, write_json_file, CommandPayload
from .mouseeventmanager import MouseActionKey

class MouseBindingStore:
    _instance: Optional["MouseBindingStore"] = None
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._map = {}
        return cls._instance
    def get_all(self) -> Dict[MouseActionKey, Dict[str, CommandPayload]]:
        return {k: dict(v) for k, v in self._map.items()}
    def set_all(self, data: Dict[MouseActionKey, Dict[str, CommandPayload]]):
        nm: Dict[MouseActionKey, Dict[str, CommandPayload]] = {}
        for k, scopes in data.items():
            if not isinstance(scopes, dict):
                raise TypeError("MouseBindingStore.set_all expects scopes dict")
            dst: Dict[str, CommandPayload] = {}
            for scope, cmd in scopes.items():
                if cmd is None:
                    continue
                if not isinstance(cmd, CommandPayload):
                    raise TypeError("MouseBindingStore requires CommandPayload")
                dst[scope] = cmd
            if dst:
                nm[k] = dst
        self._map = nm
    def set_binding(self, key: MouseActionKey, scope: str, command: Optional[Any]):
        if not scope:
            scope = "*"
        if not command:
            if key in self._map and scope in self._map[key]:
                d = self._map[key]
                d.pop(scope, None)
                if not d:
                    self._map.pop(key, None)
            return
        if not isinstance(command, CommandPayload):
            raise TypeError("MouseBindingStore.set_binding requires CommandPayload")
        norm = command
        d = self._map.setdefault(key, {})
        d[scope] = norm
    def resolve(self, widget: str, key: MouseActionKey) -> Optional[CommandPayload]:
        d = self._map.get(key)
        if not d:
            return None
        if widget in d:
            return d.get(widget)
        return d.get("*")
    def to_serializable(self) -> List[Dict[str, Any]]:
        r: List[Dict[str, Any]] = []
        for k, scopes in self._map.items():
            try:
                ser_scopes: Dict[str, Any] = {}
                for sc, payload in scopes.items():
                    ser_scopes[sc] = payload.to_dict()
                entry = {"button": k.button.name, "click": k.click_type.name, "held": [b.name for b in sorted(list(k.held_buttons), key=lambda x: x.name)], "scopes": ser_scopes}
                r.append(entry)
            except Exception:
                pass
        return r
    def load_serializable(self, data: List[Dict[str, Any]], on_error: Optional[callable] = None):
        from .mouseeventmanager import MouseButton, ClickType
        nm: Dict[MouseActionKey, Dict[str, CommandPayload]] = {}
        for e in data:
            try:
                btn = MouseButton[e.get("button")] if isinstance(e.get("button"), str) else None
                clk = ClickType[e.get("click")] if isinstance(e.get("click"), str) else None
                held_raw = e.get("held") or []
                held = []
                for h in held_raw:
                    try:
                        held.append(MouseButton[h])
                    except Exception:
                        if callable(on_error):
                            try:
                                on_error("invalid held button", None)
                            except Exception:
                                pass
                scopes = e.get("scopes") or {}
                if not btn or not clk or not isinstance(scopes, dict):
                    continue
                key = MouseActionKey(btn, clk, tuple(held))
                nm[key] = {}
                for sc, cmd in scopes.items():
                    if cmd is None:
                        continue
                    if isinstance(cmd, str):
                        try:
                            nm[key][sc] = CommandPayload.from_json(cmd)
                        except Exception as ex:
                            if callable(on_error):
                                try:
                                    on_error("invalid payload json", ex)
                                except Exception:
                                    pass
                    elif isinstance(cmd, dict):
                        try:
                            nm[key][sc] = CommandPayload.from_dict(cmd)
                        except Exception as ex:
                            if callable(on_error):
                                try:
                                    on_error("invalid payload dict", ex)
                                except Exception:
                                    pass
                    else:
                        if callable(on_error):
                            try:
                                on_error("unsupported payload type", None)
                            except Exception:
                                pass
            except Exception as ex:
                if callable(on_error):
                    try:
                        on_error("entry parse error", ex)
                    except Exception:
                        pass
        self._map = nm
    def save_to_file(self, path: str):
        try:
            p = Path(path)
            if p.parent:
                p.parent.mkdir(parents=True, exist_ok=True)
            write_json_file(p, self.to_serializable(), indent=2, ensure_ascii=False)
        except Exception:
            pass
    def load_from_file(self, path: str):
        try:
            data = read_json_file(Path(path), None)
            if isinstance(data, list):
                self.load_serializable(data)
                return True
            return False
        except Exception:
            return False
