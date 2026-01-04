from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Generic, List, Optional, Type, TypeVar

from source.common.errors import show_warning
from source.common.jsons import read_json_file, write_json_file

from ..command.payload import CommandPayload, normalize_scoped_payloads

K = TypeVar("K")


class BindingStoreBase(Generic[K]):
    _instances: Dict[type, "BindingStoreBase[Any]"] = {}
    key_type: Type[Any] = object

    def __new__(cls):
        inst = cls._instances.get(cls)
        if inst is None:
            inst = super().__new__(cls)
            inst._data = {}
            cls._instances[cls] = inst
        return inst

    def get_all(self) -> Dict[K, Dict[str, CommandPayload]]:
        return {k: dict(v) for k, v in self._data.items()}

    @classmethod
    def normalize_specs(cls, data: Dict[Any, Any]) -> Dict[K, Dict[str, CommandPayload]]:
        nm: Dict[K, Dict[str, CommandPayload]] = {}
        for key, scopes in (data or {}).items():
            if not isinstance(key, cls.key_type):
                raise TypeError(f"{cls.__name__} requires {cls.key_type.__name__} keys")
            try:
                dst = normalize_scoped_payloads(scopes)
            except Exception as e:
                raise TypeError(f"{cls.__name__} requires CommandPayload: {key}") from e
            if dst:
                nm[key] = dst
        return nm

    def set_all(self, data: Dict[Any, Any]) -> None:
        self._data = self.normalize_specs(data)

    def set_binding(self, key: K, scope: str, command: Any | None) -> None:
        if not isinstance(key, self.key_type):
            raise TypeError(f"{type(self).__name__}.set_binding key must be {self.key_type.__name__}")
        sc = str(scope).strip() if scope else "*"
        if not command:
            if key in self._data and sc in self._data[key]:
                d = self._data[key]
                d.pop(sc, None)
                if not d:
                    self._data.pop(key, None)
            return
        try:
            norm = CommandPayload.from_any(command)
        except Exception as e:
            raise TypeError(f"{type(self).__name__}.set_binding requires CommandPayload") from e
        self._data.setdefault(key, {})[sc] = norm

    def resolve(self, widget: str, key: K) -> Optional[CommandPayload]:
        d = self._data.get(key)
        if not d:
            return None
        w = str(widget) if widget else "*"
        return d.get(w) or d.get("*")

    def to_serializable(self) -> List[Dict[str, Any]]:
        raise NotImplementedError

    def load_serializable(self, data: List[Dict[str, Any]]) -> None:
        raise NotImplementedError

    def save_to_file(self, path: str) -> None:
        p = Path(path)
        ok = write_json_file(p, self.to_serializable(), indent=2, ensure_ascii=False)
        if not ok:
            show_warning(None, f"{type(self).__name__}.save_to_file failed: {path}")

    def load_from_file(self, path: str) -> bool:
        data = read_json_file(Path(path), None)
        if not isinstance(data, list):
            return False
        try:
            self.load_serializable(data)
            return True
        except Exception as e:
            show_warning(None, f"{type(self).__name__}.load_from_file failed: {path}", exc=e)
            return False
