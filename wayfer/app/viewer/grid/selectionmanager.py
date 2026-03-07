from contextlib import contextmanager
from PySide6 import QtCore
from ....utils.profiling import profiler

class SelectionManager(QtCore.QObject):
    selectionChanged = QtCore.Signal(set)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._selected = set()
        self._anchor_index = None
        self._signals_blocked = False

    def _emit(self, indices):
        if not self._signals_blocked:
            self.selectionChanged.emit(indices)

    @contextmanager
    def noemit(self):
        self._signals_blocked = True
        try:
            yield
        finally:
            self._signals_blocked = False

    @profiler.profile
    def select(self, index):
        if index not in self._selected:
            self._selected.add(index)
            self._anchor_index = index
            self._emit({index})

    def add_selection(self, indexes, last=0):
        self._selected = set(indexes) | self._selected
        self._emit(self._selected)
        self._anchor_index = indexes[last]

    def remove_selection(self, indexes):
        to_remove = set(indexes) & self._selected
        if not to_remove:
            return
        self._selected -= to_remove
        if self._anchor_index in to_remove:
            self._anchor_index = None
        self._emit(to_remove)

    def deselect(self, index):
        if index in self._selected:
            self._selected.discard(index)
            if index == self._anchor_index:
                self._anchor_index = None
            self._emit({index})

    @profiler.profile
    def toggle(self, index):
        if index in self._selected:
            self._selected.remove(index)
            if index == self._anchor_index:
                self._anchor_index = None
        else:
            self._selected.add(index)
            self._anchor_index = index
        self._emit({index})

    @profiler.profile
    def clear(self):
        if self._selected:
            temp = self._selected.copy()
            self._selected.clear()
            self._anchor_index = None
            self._emit(temp)

    def is_selected(self, index):
        return index in self._selected

    @profiler.profile
    def set_selected(self, indexes, last=0):
        temp = self._selected.copy()
        self._selected = set(indexes)
        self._anchor_index = indexes[last]
        changed = temp | self._selected
        if changed:
            self._emit(changed)

    def selected_indices(self):
        return self._selected

    def count(self):
        return len(self._selected)

    def set_anchor(self, index):
        self._anchor_index = index

    def anchor_index(self):
        return self._anchor_index
