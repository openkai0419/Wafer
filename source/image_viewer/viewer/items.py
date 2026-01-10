from __future__ import annotations

from contextlib import contextmanager
from PySide6 import QtCore

from ...common.profiling import profiler
from .selectionmanager import SelectionManager


class ViewerItems(QtCore.QObject):
    itemsChanged = QtCore.Signal()
    selectionChanged = QtCore.Signal(set)
    currentIndexChanged = QtCore.Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.paths: list[str] = []
        self.sources: list[str] = []
        self.aspect_ratios: list[float] = []
        self._selection = SelectionManager()
        self._selection.selectionChanged.connect(self._on_selection_changed)
        self._current_index: int | None = None
        self._path_to_index: dict[str, int] = {}

    def _rebuild_index(self):
        self._path_to_index = {p: i for i, p in enumerate(self.paths)}

    def _normalize_lengths(self):
        n = len(self.paths)
        if len(self.sources) != n:
            self.sources = (self.sources[:n] + [""] * n)[:n]
        if len(self.aspect_ratios) != n:
            self.aspect_ratios = (self.aspect_ratios[:n] + [0.0] * n)[:n]

    @profiler.profile
    def set_items(self, paths: list[str] | None, sources: list[str] | None, aspect_ratios: list[float] | None):
        self.paths = list(paths or [])
        self.sources = list(sources or [])
        self.aspect_ratios = list(aspect_ratios or [])
        self._normalize_lengths()
        self._rebuild_index()
        self._current_index = self._clamp_index(self._current_index)
        self._selection.clear()
        self.itemsChanged.emit()
        self.currentIndexChanged.emit(self._current_index)

    @profiler.profile
    def clear(self):
        self.set_items([], [], [])

    def count(self) -> int:
        return len(self.paths)

    def index_of_path(self, path: str) -> int | None:
        return self._path_to_index.get(path)

    def selected_indices(self) -> set[int]:
        return self._selection.selected_indices()

    def selected_count(self) -> int:
        return self._selection.count()

    def is_selected(self, index: int) -> bool:
        return self._selection.is_selected(index)

    def last_selected_index(self) -> int | None:
        return self._selection.last_added()

    @contextmanager
    def selection_noemit(self):
        with self._selection.noemit():
            yield

    @profiler.profile
    def clear_selection(self):
        self._selection.clear()

    @profiler.profile
    def toggle_selection(self, index: int):
        self._selection.toggle(index)

    @profiler.profile
    def deselect(self, index: int):
        self._selection.deselect(index)

    @profiler.profile
    def remove_selection(self, indexes: list[int] | set[int]):
        self._selection.remove_selection(list(indexes))

    @profiler.profile
    def add_selection(self, indexes: list[int], last: int = 0):
        if not indexes:
            return
        self._selection.add_selection(indexes, last=last)

    @profiler.profile
    def set_selected(self, indexes: list[int], last: int = 0):
        if not indexes:
            self._selection.clear()
            return
        self._selection.set_selected(indexes, last=last)

    def selected_paths(self) -> list[str]:
        return [self.paths[i] for i in self.selected_indices() if 0 <= i < len(self.paths)]

    def selected_sources(self) -> list[str]:
        return [self.sources[i] for i in self.selected_indices() if 0 <= i < len(self.sources)]

    def last_selected_path(self) -> str | None:
        return self.path_at(self.last_selected_index())

    def last_selected_source(self) -> str | None:
        return self.source_at(self.last_selected_index())

    def path_at(self, index: int | None) -> str | None:
        if index is None:
            return None
        if 0 <= index < len(self.paths):
            return self.paths[index]
        return None

    def source_at(self, index: int | None) -> str | None:
        if index is None:
            return None
        if 0 <= index < len(self.sources):
            return self.sources[index]
        return None

    def aspect_at(self, index: int | None) -> float | None:
        if index is None:
            return None
        if 0 <= index < len(self.aspect_ratios):
            return self.aspect_ratios[index]
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
        self._current_index = index
        self.currentIndexChanged.emit(self._current_index)

    def _preferred_anchor_index(self) -> int | None:
        last = self.last_selected_index()
        if last is not None:
            return last
        if self._current_index is not None:
            return self._current_index
        return 0 if self.paths else None

    def next_index(self, index: int | None = None, step: int = 1, wrap: bool = False) -> int | None:
        if not self.paths:
            return None
        if index is None:
            index = self._preferred_anchor_index()
        if index is None:
            return None
        nxt = index + max(1, step)
        if nxt < len(self.paths):
            return nxt
        return 0 if wrap else len(self.paths) - 1

    def prev_index(self, index: int | None = None, step: int = 1, wrap: bool = False) -> int | None:
        if not self.paths:
            return None
        if index is None:
            index = self._preferred_anchor_index()
        if index is None:
            return None
        prv = index - max(1, step)
        if prv >= 0:
            return prv
        return len(self.paths) - 1 if wrap else 0

    def next_path(self, index: int | None = None, step: int = 1, wrap: bool = False) -> str | None:
        return self.path_at(self.next_index(index=index, step=step, wrap=wrap))

    def prev_path(self, index: int | None = None, step: int = 1, wrap: bool = False) -> str | None:
        return self.path_at(self.prev_index(index=index, step=step, wrap=wrap))

    @profiler.profile
    def move_current_next(self, step: int = 1, wrap: bool = False) -> str | None:
        i = self.next_index(step=step, wrap=wrap)
        self.set_current_index(i)
        return self.path_at(i)

    @profiler.profile
    def move_current_prev(self, step: int = 1, wrap: bool = False) -> str | None:
        i = self.prev_index(step=step, wrap=wrap)
        self.set_current_index(i)
        return self.path_at(i)

    def _on_selection_changed(self, _):
        self.selectionChanged.emit(self.selected_indices())
        last = self.last_selected_index()
        if last is not None and last != self._current_index:
            self._current_index = self._clamp_index(last)
            self.currentIndexChanged.emit(self._current_index)
