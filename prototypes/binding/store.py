from __future__ import annotations
from typing import Any, Dict, Optional, List
from pathlib import Path
from ..utils import read_json_file, write_json_file
from ..mouseeventmanager import MouseActionKey


class MouseBindingStore:
    _instance: Optional["MouseBindingStore"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._map = {}
        return cls._instance

    def get_all(self) -> Dict[MouseActionKey, Dict[str, Any]]:
        return {k: dict(v) for k, v in self._map.items()}

    def set_all(self, data: Dict[MouseActionKey, Dict[str, Any]]):
        nm: Dict[MouseActionKey, Dict[str, Any]] = {}
        for k, scopes in data.items():
            if not isinstance(scopes, dict):
                continue
            dst: Dict[str, Any] = {}
            for scope, cmd in scopes.items():
                if cmd is None:
                    continue
                try:
                    from ..utils import to_payload_json, is_json_text
                    if isinstance(cmd, str) and is_json_text(cmd):
                        dst[scope] = cmd.strip()
                    else:
                        dst[scope] = to_payload_json(cmd)
                except Exception:
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
        try:
            from ..utils import to_payload_json, is_json_text
            if isinstance(command, str) and is_json_text(command):
                norm = command.strip()
            else:
                norm = to_payload_json(command)
        except Exception:
            norm = command
        d = self._map.setdefault(key, {})
        d[scope] = norm

    def resolve(self, widget: str, key: MouseActionKey) -> Optional[Any]:
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
                entry = {
                    "button": k.button.name,
                    "click": k.click_type.name,
                    "held": [b.name for b in sorted(list(k.held_buttons), key=lambda x: x.name)],
                    "scopes": scopes
                }
                r.append(entry)
            except Exception:
                pass
        return r

    def load_serializable(self, data: List[Dict[str, Any]]):
        from ..mouseeventmanager import MouseButton, ClickType
        nm: Dict[MouseActionKey, Dict[str, Any]] = {}
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
                        pass
                scopes = e.get("scopes") or {}
                if not btn or not clk or not isinstance(scopes, dict):
                    continue
                key = MouseActionKey(btn, clk, tuple(held))
                nm[key] = {}
                for sc, cmd in scopes.items():
                    if cmd is None:
                        continue
                    try:
                        from ..utils import to_payload_json, is_json_text
                        if isinstance(cmd, str) and is_json_text(cmd):
                            nm[key][sc] = cmd.strip()
                        else:
                            nm[key][sc] = to_payload_json(cmd)
                    except Exception:
                        nm[key][sc] = cmd
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