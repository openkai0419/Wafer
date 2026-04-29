from __future__ import annotations

from pathlib import Path
from collections.abc import Callable

from PySide6 import QtCore

from ....core.db.query import FileSearchEngine
from ....core.state import StateStore
from ....utils.logs import AppLogger


_STATE_NAMESPACE = "marks/overlay"
DEFAULT_RADIUS = 8
MIN_RADIUS = 4
MAX_RADIUS = 40
_MARK_KEY_PREFIX = "mark."


def _fetch_marks_sync(db_path: str | None) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    if not db_path:
        return result
    if not Path(str(db_path)).is_file():
        return result
    engine = FileSearchEngine(str(db_path))
    try:
        result = engine.get_meta_keys_by_prefix(_MARK_KEY_PREFIX)
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
        self._visible = True
        self._radius = DEFAULT_RADIUS
        self._pool = QtCore.QThreadPool.globalInstance()
        self._result_ready.connect(self._on_result_ready, QtCore.Qt.QueuedConnection)
        StateStore.instance().register(_STATE_NAMESPACE, self._save_state, self._restore_state)

    def _save_state(self) -> dict:
        return {"visible": bool(self._visible), "radius": int(self._radius)}

    def _restore_state(self, state: dict):
        if not isinstance(state, dict):
            return
        if "visible" in state:
            self._visible = bool(state["visible"])
        if "radius" in state:
            self._radius = max(MIN_RADIUS, min(MAX_RADIUS, int(state["radius"])))
        self.changed.emit()

    def is_visible(self) -> bool:
        return self._visible

    def set_visible(self, visible: bool):
        visible = bool(visible)
        if self._visible == visible:
            return
        self._visible = visible
        self.changed.emit()

    def radius(self) -> int:
        return self._radius

    def set_radius(self, value: int):
        value = max(MIN_RADIUS, min(MAX_RADIUS, int(value)))
        if value == self._radius:
            return
        self._radius = value
        self.changed.emit()

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
