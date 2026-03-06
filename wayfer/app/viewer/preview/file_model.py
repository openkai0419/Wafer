from __future__ import annotations

from PySide6 import QtCore

from ....utils.profiling import profiler

class FileViewModel(QtCore.QObject):
    itemsChanged = QtCore.Signal()
    currentIndexChanged = QtCore.Signal(object)
    pathChanged = QtCore.Signal(object)

    def __init__(self, dbpath_getter=None, parent=None):
        super().__init__(parent)
        self.paths: list[str] = []
        self.sources: list[str] = []
        self._current_index: int | None = None
        self._display_path: str | None = None
        self._path_to_index: dict[str, int] = {}
        self._dbpath_getter = dbpath_getter

    @property
    def dbpath(self) -> str | None:
        if self._dbpath_getter is not None:
            return self._dbpath_getter()
        return None

    def _rebuild_index(self):
        self._path_to_index = {p: i for i, p in enumerate(self.paths)}

    def _normalize_lengths(self):
        n = len(self.paths)
        if len(self.sources) != n:
            self.sources = (self.sources[:n] + [""] * n)[:n]

    @profiler.profile
    def set_items(self, paths: list[str] | None, sources: list[str] | None):
        self.paths = list(paths or [])
        self.sources = list(sources or [])
        self._normalize_lengths()
        self._rebuild_index()
        self._current_index = self._path_to_index.get(self._display_path)
        self.itemsChanged.emit()
        self.currentIndexChanged.emit(self._current_index)

    def count(self) -> int:
        return len(self.paths)

    def path(self) -> str | None:
        return self._display_path

    def index_of_path(self, path: str) -> int | None:
        return self._path_to_index.get(path)

    def path_at(self, index: int | None) -> str | None:
        if index is None:
            return None
        if 0 <= index < len(self.paths):
            return self.paths[index]
        return None

    def _clamp_index(self, index: int | None) -> int | None:
        if index is None:
            return None
        if not self.paths:
            return None
        return max(0, min(index, len(self.paths) - 1))

    def current_index(self) -> int | None:
        return self._current_index

    @profiler.profile
    def set_current_index(self, index: int | None):
        index = self._clamp_index(index)
        if index == self._current_index:
            return
        old_path = self._display_path
        self._current_index = index
        self._display_path = self.path_at(index)
        self.currentIndexChanged.emit(self._current_index)
        if self._display_path != old_path:
            self.pathChanged.emit(self._display_path)

    @profiler.profile
    def set_path(self, path: str | None):
        if not path:
            return
        if path == self._display_path:
            return
        old_path = self._display_path
        self._display_path = path
        idx = self.index_of_path(path)
        if idx is not None:
            self._current_index = idx
        else:
            self.paths.append(path)
            self.sources.append("")
            self._path_to_index[path] = len(self.paths) - 1
            self._current_index = len(self.paths) - 1
        self.currentIndexChanged.emit(self._current_index)
        if path != old_path:
            self.pathChanged.emit(path)

    def next_index(self, index: int | None = None, step: int = 1, loop: bool = False) -> int | None:
        if not self.paths:
            return None
        if index is None:
            index = self._current_index
        if index is None:
            return 0 if self.paths else None
        nxt = index + max(1, step)
        if nxt < len(self.paths):
            return nxt
        return 0 if loop else len(self.paths) - 1

    def prev_index(self, index: int | None = None, step: int = 1, loop: bool = False) -> int | None:
        if not self.paths:
            return None
        if index is None:
            index = self._current_index
        if index is None:
            return 0 if self.paths else None
        prv = index - max(1, step)
        if prv >= 0:
            return prv
        return len(self.paths) - 1 if loop else 0

    @profiler.profile
    def move_current_next(self, step: int = 1, loop: bool = False) -> str | None:
        i = self.next_index(step=step, loop=loop)
        self.set_current_index(i)
        return self.path_at(i)

    @profiler.profile
    def move_current_prev(self, step: int = 1, loop: bool = False) -> str | None:
        i = self.prev_index(step=step, loop=loop)
        self.set_current_index(i)
        return self.path_at(i)
