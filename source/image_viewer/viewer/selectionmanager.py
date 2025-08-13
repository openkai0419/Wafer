from contextlib import contextmanager

from PySide6 import QtCore


class SelectionManager(QtCore.QObject):
    selectionChanged = QtCore.Signal(set)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._selected = set()
        self._last_added = None
        self._signals_blocked = False

    def _emit(self, indices: set):
        if not self._signals_blocked:
            self.selectionChanged.emit(indices)
    
    @contextmanager
    def noemit(self):
        self._signals_blocked = True
        try:
            yield
        finally:
            self._signals_blocked = False

    def select(self, index: int):
        if index not in self._selected:
            self._selected.add(index)
            self._last_added = index
            self._emit({index})
    
    def add_selection(self, indexes, last=0):
        self._selected = set(indexes) | self._selected
        self._emit(self._selected)
        self._last_added = indexes[last]

    def remove_selection(self, indexes):
        to_remove = set(indexes) & self._selected
        if not to_remove:
            return
        self._selected -= to_remove
        if self._last_added in to_remove:
            self._last_added = None
        self._emit(to_remove)

    def deselect(self, index: int):
        if index in self._selected:
            self._selected.discard(index)
            if index == self._last_added:
                self._last_added = None  # 一旦クリア
            self._emit({index})

    def toggle(self, index: int):
        if index in self._selected:
            self._selected.remove(index)
            if index == self._last_added:
                self._last_added = None
        else:
            self._selected.add(index)
            self._last_added = index
        self._emit({index})

    def clear(self):
        if self._selected:
            temp = self._selected.copy()
            self._selected.clear()
            self._last_added = None  # クリア
            self._emit(temp)

    def is_selected(self, index: int) -> bool:
        return index in self._selected

    def set_selected(self, indexes, last=0):
        temp = self._selected.copy()
        self._selected = set(indexes)
        self._last_added = indexes[last]
        changed = temp | self._selected
        if changed:
            self._emit(changed)

    def selected_indices(self):
        return self._selected

    def count(self) -> int:
        return len(self._selected)

    def set_last(self, index):
        self._last_added = index

    def last_added(self):
        return self._last_added
