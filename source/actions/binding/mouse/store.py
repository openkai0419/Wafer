from __future__ import annotations

from typing import Any, Dict, List

from ..store_base import BindingStoreBase
from ...command.payload import CommandPayload
from .mouseeventmanager import MouseActionKey


class MouseBindingStore(BindingStoreBase[MouseActionKey]):
    key_type = MouseActionKey
    def to_serializable(self) -> List[Dict[str, Any]]:
        return [{"key": k.to_dict(), "scopes": {sc: p.to_dict() for sc, p in scopes.items()}} for k, scopes in self._data.items()]

    def load_serializable(self, data: List[Dict[str, Any]]) -> None:
        nm: Dict[MouseActionKey, Dict[str, CommandPayload]] = {}
        for e in data:
            if not isinstance(e, dict):
                continue
            key_obj = e.get("key")
            scopes = e.get("scopes")
            if not isinstance(scopes, dict):
                continue
            try:
                key = MouseActionKey.from_dict(key_obj)
            except Exception:
                continue
            dst: Dict[str, CommandPayload] = {}
            for sc, obj in scopes.items():
                if obj is None:
                    continue
                try:
                    dst[str(sc)] = CommandPayload.from_any(obj)
                except Exception:
                    continue
            if dst:
                nm[key] = dst
        self._data = nm
