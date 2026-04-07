from __future__ import annotations

from pathlib import Path
from typing import Any, Generic, TypeVar

from ....utils.logs import AppLogger
from ....utils.json_io import read_json_file, write_json_file

from ..command.payload import CommandPayload, normalize_scoped_payloads

K = TypeVar("K")


def resolve_for_widget(data: dict[Any, dict[str, Any]], widget_name: str) -> dict[Any, Any]:
    bindings = {}
    for key, scopes in data.items():
        target = scopes.get(widget_name) or scopes.get("*")
        if target:
            bindings[key] = target
    return bindings


class BindingStoreBase(Generic[K]):
    _instance: BindingStoreBase[Any] | None = None
    key_type: type[Any] = object

    @classmethod
    def instance(cls) -> BindingStoreBase[K]:
        if cls._instance is None:
            inst = object.__new__(cls)
            inst._data = {}
            cls._instance = inst
        return cls._instance

    def get_all(self) -> dict[K, dict[str, CommandPayload]]:
        return {k: dict(v) for k, v in self._data.items()}

    @classmethod
    def normalize_specs(cls, data: dict[Any, Any]) -> dict[K, dict[str, CommandPayload]]:
        nm: dict[K, dict[str, CommandPayload]] = {}
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

    def set_all(self, data: dict[Any, Any]) -> None:
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

    def resolve(self, widget: str, key: K) -> CommandPayload | None:
        d = self._data.get(key)
        if not d:
            return None
        w = str(widget) if widget else "*"
        return d.get(w) or d.get("*")

    def _seed_file_path(self) -> str | None:
        return None

    def _seed_data(self) -> dict[K, dict[str, CommandPayload]]:
        path = self._seed_file_path()
        if path:
            return self._load_seed_file(path)
        return {}

    def _load_seed_file(self, path: str) -> dict[K, dict[str, CommandPayload]]:
        data = read_json_file(Path(path), None)
        if not isinstance(data, dict):
            return {}
        items = data.get("items")
        if not isinstance(items, list):
            return {}
        raw = self._from_items(items)
        return {k: {sc: p for sc, p in scopes.items() if p is not None} for k, scopes in raw.items() if any(p is not None for p in scopes.values())}

    def _payload_equal(self, a: CommandPayload, b: CommandPayload) -> bool:
        return a.id == b.id and (a.args or {}) == (b.args or {})

    def _diff_data(self, cur: dict[K, dict[str, CommandPayload]], seed: dict[K, dict[str, CommandPayload]]) -> dict[K, dict[str, CommandPayload | None]]:
        out: dict[K, dict[str, CommandPayload | None]] = {}
        keys = set(seed.keys()) | set(cur.keys())
        for k in keys:
            cur_scopes = cur.get(k, {})
            seed_scopes = seed.get(k, {})
            changes: dict[str, CommandPayload | None] = {}
            for sc, c in cur_scopes.items():
                s = seed_scopes.get(sc)
                if s is None or not self._payload_equal(c, s):
                    changes[sc] = c
            for sc in seed_scopes:
                if sc not in cur_scopes:
                    changes[sc] = None
            if changes:
                out[k] = changes
        return out

    def _apply_diff(self, base: dict[K, dict[str, CommandPayload]], diff: dict[K, dict[str, CommandPayload | None]]) -> dict[K, dict[str, CommandPayload]]:
        for k, scopes in diff.items():
            if k not in base:
                base[k] = {}
            dst = base.get(k, {})
            for sc, payload in scopes.items():
                if payload is None:
                    dst.pop(sc, None)
                else:
                    dst[sc] = payload
            if dst:
                base[k] = dst
            else:
                base.pop(k, None)
        return base

    def _to_items(self, data: dict[K, dict[str, CommandPayload | None]]) -> list[dict[str, Any]]:
        r: list[dict[str, Any]] = []
        for k, scopes in data.items():
            r.append({"key": k.to_dict(), "scopes": {sc: (p.to_dict() if isinstance(p, CommandPayload) else None) for sc, p in scopes.items()}})
        return r

    def _from_items(self, data: list[dict[str, Any]]) -> dict[K, dict[str, CommandPayload | None]]:
        nm: dict[K, dict[str, CommandPayload | None]] = {}
        for e in data:
            if not isinstance(e, dict):
                continue
            key_obj = e.get("key")
            scopes = e.get("scopes")
            if not isinstance(scopes, dict):
                continue
            try:
                key = self.key_type.from_dict(key_obj)
            except Exception:
                continue
            dst: dict[str, CommandPayload | None] = {}
            for sc, obj in scopes.items():
                if obj is None:
                    dst[str(sc)] = None
                    continue
                try:
                    dst[str(sc)] = CommandPayload.from_any(obj)
                except Exception:
                    continue
            if dst:
                nm[key] = dst
        return nm

    def save_to_file(self, path: str) -> None:
        p = Path(path)
        seed = self._seed_data()
        diff = self._diff_data(self._data, seed)
        payload = {"items": self._to_items(diff)}
        ok = write_json_file(p, payload, indent=2, ensure_ascii=False)
        if not ok:
            AppLogger.warning(f"{type(self).__name__}.save_to_file failed: {path}")

    def load_from_file(self, path: str) -> bool:
        data = read_json_file(Path(path), None)
        if not isinstance(data, dict):
            return False
        items = data.get("items")
        if not isinstance(items, list):
            return False
        try:
            seed = self._seed_data()
            diff = self._from_items(items)
            self._data = self._apply_diff(seed, diff)
            return True
        except Exception as e:
            AppLogger.warning(f"{type(self).__name__}.load_from_file failed: {path}", exc=e)
            return False
