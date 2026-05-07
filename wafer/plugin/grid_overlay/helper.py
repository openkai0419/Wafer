from __future__ import annotations

from pathlib import Path
from collections.abc import Iterable

from PySide6 import QtCore

from ...core.db.query import FileSearchEngine
from ...core.qt.dispatcher import Dispatcher
from ...core.qt.thread import utility_pool
from ...utils.logs import AppLogger


class OverlayHelper(QtCore.QObject):
    changed = QtCore.Signal()

    def __init__(self, scope: str, key_prefix: str, parent: QtCore.QObject | None = None):
        super().__init__(parent)
        self._scope = str(scope or "*")
        self._key_prefix = str(key_prefix or "")
        self._cache: dict[str, tuple[str, ...]] = {}
        self._host = None
        self._bound_update = None
        self._seq = 0
        self._loaded = False
        self._last_paths: tuple[str, ...] | None = None
        self._dispatcher = Dispatcher(utility_pool, parent=self)

    def bind_host(self, host) -> None:
        self._host = host
        if self._bound_update is not None and self._bound_update != host.request_update:
            try:
                self.changed.disconnect(self._bound_update)
            except (TypeError, RuntimeError):
                pass
        if self._bound_update == host.request_update:
            return
        self.changed.connect(host.request_update)
        self._bound_update = host.request_update

    def values_for(self, path: str) -> tuple[str, ...]:
        return self._cache.get(str(path), ())

    def is_loaded(self) -> bool:
        return self._loaded

    def clear(self) -> None:
        if not self._cache and not self._loaded:
            return
        self._cache = {}
        self._loaded = False
        self._last_paths = None
        self.changed.emit()

    def refresh(self, paths: Iterable[str] | None = None, *, force: bool = False) -> None:
        path_tuple = None if paths is None else tuple(dict.fromkeys(str(path) for path in paths if path))
        if not force and self._loaded and path_tuple == self._last_paths:
            return
        db_path = self._database_path()
        self._seq += 1
        seq = self._seq
        self._last_paths = path_tuple
        if not db_path or not Path(str(db_path)).is_file() or not self._key_prefix:
            self._on_result(seq, {})
            return
        fetch_paths = list(path_tuple) if path_tuple is not None else None

        def task():
            result = self._fetch(db_path, fetch_paths)
            self._dispatcher.invoke(lambda: self._on_result(seq, result))

        self._dispatcher.post(task, priority=6)

    def _database_path(self) -> str | None:
        if self._host is None:
            return None
        try:
            return self._host.database_path()
        except Exception as e:
            AppLogger.warning("[OverlayHelper] database path lookup failed", exc=e)
            return None

    def _fetch(self, db_path: str, paths: list[str] | None) -> dict[str, tuple[str, ...]]:
        engine = FileSearchEngine(str(db_path))
        try:
            result = engine.get_kv_keys_by_prefix(self._scope, self._key_prefix, paths)
            return {path: tuple(values) for path, values in result.items() if values}
        except Exception as e:
            AppLogger.warning("[OverlayHelper] fetch failed", exc=e)
            return {}
        finally:
            engine.close()

    @QtCore.Slot(int, dict)
    def _on_result(self, seq: int, result: dict[str, tuple[str, ...]]) -> None:
        if seq != self._seq:
            return
        self._cache = dict(result)
        self._loaded = True
        self.changed.emit()
