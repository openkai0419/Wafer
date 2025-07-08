
import copy

from PySide6 import QtWidgets, QtGui, QtCore

class SelectionManager(QtCore.QObject):
    selectionChanged = QtCore.Signal(set)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._selected = set()

    def select(self, index: int):
        self._selected.add(index)
        self.selectionChanged.emit(set(index))

    def deselect(self, index: int):
        self._selected.discard(index)
        self.selectionChanged.emit(set(index))

    def toggle(self, index: int):
        if index in self._selected:
            self._selected.remove(index)
        else:
            self._selected.add(index)
        self.selectionChanged.emit(set(index))

    def clear(self):
        temp = copy.copy(self._selected)
        self._selected.clear()
        self.selectionChanged.emit(temp)

    def is_selected(self, index: int) -> bool:
        return index in self._selected

    def set_selected(self, indexes):
        temp = copy.copy(self._selected)
        self._selected = set(indexes)
        outind = temp | self._selected
        self.selectionChanged.emit(outind)

    def selected_indices(self):
        return sorted(self._selected)

    def count(self) -> int:
        return len(self._selected)
    