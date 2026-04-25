from __future__ import annotations

import sqlite3
from pathlib import Path
from collections.abc import Callable

from PySide6 import QtCore

from ....utils.logs import AppLogger


_SQL_CHUNK = 900


def _fetch_marks_sync(db_path: str | None, paths: list[str]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    if not db_path or not paths:
        return result
    if not Path(str(db_path)).is_file():
        return result
    try:
        uri = Path(db_path).resolve().as_uri()
        conn = sqlite3.connect(f"{uri}?mode=ro", uri=True, timeout=1.0)
        try:
            for start in range(0, len(paths), _SQL_CHUNK):
                chunk = paths[start : start + _SQL_CHUNK]
                placeholders = ",".join("?" * len(chunk))
                rows = conn.execute(
                    f"SELECT i.path, t.key FROM tags t JOIN sources s ON s.file_hash = t.file_hash JOIN files i ON i.source = s.source WHERE i.path IN ({placeholders}) AND t.key LIKE 'mark.%'",
                    chunk,
                ).fetchall()
                for path, key in rows:
                    if not key:
                        continue
                    mid = key.split(".", 1)[1] if "." in key else ""
                    if not mid:
                        continue
                    result.setdefault(path, []).append(mid)
        finally:
            conn.close()
    except Exception as e:
        AppLogger.warning("[MarkOverlay] fetch failed", exc=e)
    for p, ids in result.items():
        result[p] = sorted(set(ids), key=lambda x: (len(x), x))
    return result


class _MarkFetchTask(QtCore.QRunnable):
    def __init__(self, db_path: str | None, paths: list[str], generation: int, replace_all: bool, sink: "MarkOverlayService"):
        super().__init__()
        self._db_path = db_path
        self._paths = paths
        self._generation = generation
        self._replace_all = replace_all
        self._sink = sink

    def run(self):
        result = _fetch_marks_sync(self._db_path, self._paths)
        try:
            self._sink._result_ready.emit(self._generation, list(self._paths), result, self._replace_all)
        except RuntimeError:
            pass


class MarkOverlayService(QtCore.QObject):
    changed = QtCore.Signal()
    _result_ready = QtCore.Signal(int, list, dict, bool)

    _instance: MarkOverlayService | None = None

    def __init__(self, dbpath_getter: Callable[[], str | None], parent: QtCore.QObject | None = None):
        super().__init__(parent)
        self._dbpath_getter = dbpath_getter
        self._marks: dict[str, list[str]] = {}
        self._known_paths: list[str] = []
        self._generation = 0
        self._latest_replace_gen = 0
        self._pool = QtCore.QThreadPool.globalInstance()
        self._result_ready.connect(self._on_result_ready, QtCore.Qt.QueuedConnection)
        MarkOverlayService._instance = self

    @classmethod
    def instance(cls) -> MarkOverlayService | None:
        return cls._instance

    def marks_for(self, path: str) -> list[str]:
        return self._marks.get(path, [])

    def set_paths(self, paths: list[str]):
        self._known_paths = list(paths or [])
        self._marks = {}
        self._submit(self._known_paths, replace_all=True)

    def refresh_paths(self, paths: list[str]):
        if not paths:
            return
        self._submit(list(paths), replace_all=False)

    def refresh_all(self):
        if self._known_paths:
            self._submit(list(self._known_paths), replace_all=True)

    def _submit(self, paths: list[str], *, replace_all: bool):
        self._generation += 1
        gen = self._generation
        if replace_all:
            self._latest_replace_gen = gen
        db_path = self._dbpath_getter() if self._dbpath_getter else None
        task = _MarkFetchTask(db_path, list(paths), gen, replace_all, self)
        self._pool.start(task)

    @QtCore.Slot(int, list, dict, bool)
    def _on_result_ready(self, generation: int, paths: list, result: dict, replace_all: bool):
        if generation < self._latest_replace_gen:
            return
        if replace_all:
            self._marks = {p: result.get(p, []) for p in paths if result.get(p)}
        else:
            known = set(self._known_paths) if self._known_paths else None
            for p in paths:
                if known is not None and p not in known:
                    continue
                ids = result.get(p)
                if ids:
                    self._marks[p] = ids
                else:
                    self._marks.pop(p, None)
        self.changed.emit()
