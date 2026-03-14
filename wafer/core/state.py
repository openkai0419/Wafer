from __future__ import annotations

import threading
from typing import Any, Callable

from ..utils.logs import AppLogger

SaveFn = Callable[[], dict[str, Any]]
RestoreFn = Callable[[dict[str, Any]], None]


class StateStore:
    _instance: StateStore | None = None

    @classmethod
    def instance(cls) -> StateStore:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._entries: dict[str, tuple[SaveFn, RestoreFn]] = {}
        self._pending: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def register(self, namespace: str, save: SaveFn, restore: RestoreFn):
        with self._lock:
            self._entries[namespace] = (save, restore)
            pending = self._pending.pop(namespace, None)
        if pending is not None:
            try:
                restore(pending)
            except Exception as e:
                AppLogger.warning(f"StateStore deferred restore failed for '{namespace}': {e}", exc=e)

    def unregister(self, namespace: str):
        with self._lock:
            self._entries.pop(namespace, None)

    def save_all(self) -> dict[str, Any]:
        with self._lock:
            entries = dict(self._entries)
        result: dict[str, Any] = {}
        for ns, (save, _) in entries.items():
            try:
                state = save()
            except Exception as e:
                AppLogger.warning(f"StateStore save failed for '{ns}': {e}", exc=e)
                continue
            if state:
                result[ns] = state
        return result

    def restore_all(self, states: dict[str, Any]):
        with self._lock:
            self._pending.clear()
            resolved = []
            pending = []
            for ns, state in states.items():
                if not isinstance(state, dict):
                    continue
                entry = self._entries.get(ns)
                if entry is not None:
                    resolved.append((ns, entry[1], state))
                else:
                    pending.append((ns, state))
            for ns, state in pending:
                self._pending[ns] = state
        for ns, restore_fn, state in resolved:
            try:
                restore_fn(state)
            except Exception as e:
                AppLogger.warning(f"StateStore restore failed for '{ns}': {e}", exc=e)

    def clear(self):
        with self._lock:
            self._entries.clear()
            self._pending.clear()
