from __future__ import annotations

from pathlib import Path
from collections.abc import Callable

from PySide6 import QtCore

from ....core.app_settings import app_settings
from ....core.db.query import FileSearchEngine
from ....core.qt.rate_limit import qt_debounce
from ....utils.logs import AppLogger


_RADIUS_KEY = "marks/overlay_radius"
_VISIBLE_KEY = "marks/overlay_visible"
DEFAULT_RADIUS = 8
MIN_RADIUS = 4
MAX_RADIUS = 40
_COMMIT_DEBOUNCE_MS = 300
_MARK_KEY_PREFIX = "mark."


def _fetch_marks_sync(db_path: str | None) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    if not db_path:
        return result
    if not Path(str(db_path)).is_file():
        return result
    engine = FileSearchEngine(str(db_path))
    try:
        result = engine.get_tag_keys_by_prefix(_MARK_KEY_PREFIX)
    except Exception as e:
        AppLogger.warning("[MarkOverlay] fetch failed", exc=e)
    finally:
        engine.close()
    for p, ids in result.items():
        result[p] = sorted(set(ids), key=lambda x: (len(x), x))
    return result


class _MarkFetchTask(QtCore.QRunnable):
    def __init__(self, db_path: str | None, reload_seq: int, sink: MarkOverlayService):
        super().__init__()
        self._db_path = db_path
        self._reload_seq = reload_seq
        self._sink = sink

    def run(self):
        result = _fetch_marks_sync(self._db_path)
        try:
            self._sink._result_ready.emit(self._reload_seq, result)
        except RuntimeError:
            pass


class MarkOverlayService(QtCore.QObject):
    changed = QtCore.Signal()
    _result_ready = QtCore.Signal(int, dict)

    def __init__(self, dbpath_getter: Callable[[], str | None], parent: QtCore.QObject | None = None):
        super().__init__(parent)
        self._dbpath_getter = dbpath_getter
        self._marks: dict[str, list[str]] = {}
        self._reload_seq = 0
        self._visible = bool(app_settings.get(_VISIBLE_KEY, 1, int))
        self._radius = max(MIN_RADIUS, min(MAX_RADIUS, int(app_settings.get(_RADIUS_KEY, DEFAULT_RADIUS, int))))
        self._pool = QtCore.QThreadPool.globalInstance()
        self._result_ready.connect(self._on_result_ready, QtCore.Qt.QueuedConnection)

    def is_visible(self) -> bool:
        return self._visible

    def set_visible(self, visible: bool):
        visible = bool(visible)
        if self._visible == visible:
            return
        self._visible = visible
        app_settings.set(_VISIBLE_KEY, 1 if visible else 0)
        self._commit_settings()
        self.changed.emit()

    def radius(self) -> int:
        return self._radius

    def set_radius(self, value: int):
        value = max(MIN_RADIUS, min(MAX_RADIUS, int(value)))
        if value == self._radius:
            return
        self._radius = value
        app_settings.set(_RADIUS_KEY, value)
        self._commit_settings()
        self.changed.emit()

    @qt_debounce(_COMMIT_DEBOUNCE_MS)
    def _commit_settings(self):
        app_settings.commit()

    def marks_for(self, path: str) -> list[str]:
        return self._marks.get(path, [])

    def reload(self):
        self._reload_seq += 1
        db_path = self._dbpath_getter() if self._dbpath_getter else None
        self._pool.start(_MarkFetchTask(db_path, self._reload_seq, self))

    @QtCore.Slot(int, dict)
    def _on_result_ready(self, reload_seq: int, result: dict):
        if reload_seq != self._reload_seq:
            return
        self._marks = {p: ids for p, ids in result.items() if ids}
        self.changed.emit()
