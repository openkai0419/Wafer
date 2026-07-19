from __future__ import annotations

import threading
from collections.abc import Callable, Iterable

from .config import PluginConfig
from ..utils.logs import AppLogger

MODE_BLACKLIST = "blacklist"
MODE_WHITELIST = "whitelist"

RELOAD_TOPIC = "keyfilter.reload"

_config = PluginConfig("key_filter", {"filters": {}, "sort_mode": 1, "sort_ascending": False})
_lock = threading.Lock()


def _normalize(raw: dict) -> dict[str, tuple[str, frozenset[str]]]:
    result: dict[str, tuple[str, frozenset[str]]] = {}
    for prefix, entry in (raw or {}).items():
        if not isinstance(entry, dict):
            continue
        mode = entry.get("mode", MODE_BLACKLIST)
        if mode not in (MODE_BLACKLIST, MODE_WHITELIST):
            mode = MODE_BLACKLIST
        result[prefix] = (mode, frozenset(entry.get("keys") or ()))
    return result


class KeyFilter:
    _cache: dict[str, tuple[str, frozenset[str]]] | None = None
    _subscribers: list[Callable[[str], None]] = []

    @classmethod
    def _filters(cls) -> dict[str, tuple[str, frozenset[str]]]:
        if cls._cache is None:
            cls._cache = _normalize(_config.load().get("filters") or {})
        return cls._cache

    @classmethod
    def reload(cls) -> None:
        cls._cache = _normalize(_config.load().get("filters") or {})

    @classmethod
    def get(cls, prefix: str) -> tuple[str, frozenset[str]]:
        return cls._filters().get(prefix) or (MODE_BLACKLIST, frozenset())

    @classmethod
    def is_enabled(cls, prefix: str, key: str) -> bool:
        entry = cls._filters().get(prefix)
        if not entry:
            return True
        mode, keys = entry
        return key in keys if mode == MODE_WHITELIST else key not in keys

    @classmethod
    def predicate(cls, prefix: str) -> Callable[[str], bool] | None:
        entry = cls._filters().get(prefix)
        if not entry:
            return None
        mode, keys = entry
        if mode == MODE_WHITELIST:
            return keys.__contains__
        if not keys:
            return None
        return lambda k: k not in keys

    @classmethod
    def blocked_keys(
        cls,
        prefix: str,
        known_keys: Iterable[str] | None = None,
        *,
        mode: str | None = None,
        keys: Iterable[str] | None = None,
    ) -> list[str]:
        if mode is None:
            mode, keys = cls.get(prefix)
        selected = set(keys or ())
        blocked = selected if mode == MODE_BLACKLIST else (set(known_keys or ()) - selected)
        return [f"{prefix}.{k}" for k in sorted(blocked)]

    @classmethod
    def set_keys(cls, prefix: str, mode: str, keys: Iterable[str]) -> None:
        if mode not in (MODE_BLACKLIST, MODE_WHITELIST):
            mode = MODE_BLACKLIST
        with _lock:
            filters = dict(_config.load().get("filters") or {})
            filters[prefix] = {"mode": mode, "keys": sorted(set(keys))}
            _config.save(filters=filters)
        cls.reload()
        cls._broadcast_reload()
        cls._notify(prefix)

    @classmethod
    def set_key_enabled(cls, prefix: str, key: str, enabled: bool) -> None:
        cls.apply_key_states(prefix, {key: enabled})

    @classmethod
    def apply_key_states(cls, prefix: str, states: dict[str, bool]) -> None:
        if not states:
            return
        mode, keys = cls.get(prefix)
        in_set = mode == MODE_WHITELIST
        new_keys = set(keys)
        for key, enabled in states.items():
            if enabled == in_set:
                new_keys.add(key)
            else:
                new_keys.discard(key)
        cls.set_keys(prefix, mode, new_keys)

    @staticmethod
    def send_delete_keys(db_names: Iterable[str], keys: Iterable[str], collector: str, *, re_collect: bool) -> None:
        from ..core.commands.binding.instance_registry import InstanceRegistry

        node = InstanceRegistry.instance().resolve_node()
        if node is None:
            AppLogger.warning("[MetadataFilter] No IPC node available; skipped delete/re-collect")
            return
        payload = {"keys": list(keys), "collector": collector, "re_collect": re_collect}
        for db in db_names:
            node.send_reliable("delete.keys", payload, dst="indexer", db=db)

    @classmethod
    def read_sort(cls) -> tuple[int, bool]:
        cfg = _config.load()
        mode = cfg.get("sort_mode", 1)
        return (mode if mode in (0, 1) else 1), bool(cfg.get("sort_ascending", False))

    @classmethod
    def write_sort(cls, mode: int, ascending: bool) -> None:
        with _lock:
            _config.save(sort_mode=int(mode), sort_ascending=bool(ascending))

    @classmethod
    def subscribe(cls, callback: Callable[[str], None]) -> None:
        if callback not in cls._subscribers:
            cls._subscribers.append(callback)

    @classmethod
    def unsubscribe(cls, callback: Callable[[str], None]) -> None:
        if callback in cls._subscribers:
            cls._subscribers.remove(callback)

    @classmethod
    def _notify(cls, prefix: str) -> None:
        for callback in list(cls._subscribers):
            try:
                callback(prefix)
            except Exception as e:
                AppLogger.warning(f"[KeyFilter] subscriber failed: {e}", exc=e)

    @staticmethod
    def _broadcast_reload() -> None:
        from ..core.commands.binding.instance_registry import InstanceRegistry
        from ..core.db.dispatch import send_to_db_scope

        node = InstanceRegistry.instance().resolve_node()
        if node is None:
            return
        send_to_db_scope(node, RELOAD_TOPIC, {}, db_scope="*")
