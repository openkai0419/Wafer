from __future__ import annotations

from contextlib import contextmanager
from PySide6 import QtCore

from ....utils.profiling import profiler
from .selectionmanager import SelectionManager


class GridItemModel(QtCore.QObject):
    itemsChanged = QtCore.Signal()
    selectionChanged = QtCore.Signal(set)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.paths: list[str] = []
        self.sources: list[str] = []
        self.aspect_ratios: list[float] = []
        self.avg_aspect: float = 1.0
        self._selection = SelectionManager()
        self._selection.selectionChanged.connect(self._on_selection_changed)
        self._path_to_index: dict[str, int] = {}

    def _rebuild_index(self):
        self._path_to_index = {p: i for i, p in enumerate(self.paths)}

    def _normalize_lengths(self):
        n = len(self.paths)
        if len(self.sources) != n:
            self.sources = (self.sources[:n] + [""] * n)[:n]
        if len(self.aspect_ratios) != n:
            self.aspect_ratios = (self.aspect_ratios[:n] + [1.0] * n)[:n]

    @profiler.profile
    def set_items(self, paths: list[str] | None, sources: list[str] | None, aspect_ratios: list[float] | None):
        self.paths = list(paths or [])
        self.sources = list(sources or [])
        self.aspect_ratios = list(aspect_ratios or [])
        self._normalize_lengths()
        self._rebuild_index()
        ratios = self.aspect_ratios
        self.avg_aspect = sum(r or 1.0 for r in ratios) / len(ratios) if ratios else 1.0
        self._selection.clear()
        self.itemsChanged.emit()

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
        return self._selection.anchor_index()

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

    def _on_selection_changed(self, _):
        self.selectionChanged.emit(self.selected_indices())
