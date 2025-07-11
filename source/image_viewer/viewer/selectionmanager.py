import copy
from PySide6 import QtCore

class SelectionManager(QtCore.QObject):
    selectionChanged = QtCore.Signal(set)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._selected = set()
        self._last_added = None  # ← 追加

    def select(self, index: int):
        if index not in self._selected:
            self._selected.add(index)
            self._last_added = index
            self.selectionChanged.emit({index})
    
    def add_selection(self, indexes, last=0):
        self._selected = set(indexes) | self._selected
        self.selectionChanged.emit(self._selected)
        self._last_added = indexes[last]


    def deselect(self, index: int):
        if index in self._selected:
            self._selected.discard(index)
            if index == self._last_added:
                self._last_added = None  # 一旦クリア
            self.selectionChanged.emit({index})

    def toggle(self, index: int):
        if index in self._selected:
            self._selected.remove(index)
            if index == self._last_added:
                self._last_added = None
        else:
            self._selected.add(index)
            self._last_added = index
        self.selectionChanged.emit({index})

    def clear(self):
        if self._selected:
            temp = self._selected.copy()
            self._selected.clear()
            self._last_added = None  # クリア
            self.selectionChanged.emit(temp)

    def is_selected(self, index: int) -> bool:
        return index in self._selected

    def set_selected(self, indexes, last=0):
        temp = self._selected.copy()
        self._selected = set(indexes)
        changed = temp | self._selected
        if changed:
            self._last_added = indexes[last]
            self.selectionChanged.emit(changed)

    def selected_indices(self):
        return sorted(self._selected)

    def count(self) -> int:
        return len(self._selected)

    def last_added(self):
        return self._last_added
