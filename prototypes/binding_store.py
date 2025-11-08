from __future__ import annotations
from typing import Dict, Optional
from .mouseeventmanager import MouseActionKey


class MouseBindingStore:
    _instance: Optional["MouseBindingStore"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._map = {}
        return cls._instance

    def get_all(self) -> Dict[MouseActionKey, Dict[str, str]]:
        return {k: dict(v) for k, v in self._map.items()}

    def set_all(self, data: Dict[MouseActionKey, Dict[str, str]]):
        self._map = {k: dict(v) for k, v in data.items()}

    def set_binding(self, key: MouseActionKey, scope: str, command: Optional[str]):
        if not scope:
            scope = "*"
        if not command:
            if key in self._map and scope in self._map[key]:
                d = self._map[key]
                d.pop(scope, None)
                if not d:
                    self._map.pop(key, None)
            return
        d = self._map.setdefault(key, {})
        d[scope] = command

    def resolve(self, widget: str, key: MouseActionKey) -> Optional[str]:
        d = self._map.get(key)
        if not d:
            return None
        if widget in d:
            return d.get(widget)
        return d.get("*")
