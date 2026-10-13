from __future__ import annotations

import os
from collections.abc import Iterable

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from wafer.qt.commands.bridge import ActionKit
from wafer.qt.common.dpi import dpix

ROW_ROLE = Qt.UserRole + 1
COLOR_ROLE = Qt.UserRole + 2
ICON_SIZE = 40
COLOR_BAR = 4


class FileListModel(QtCore.QAbstractListModel):
    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self.owner = owner
        self.paths: list[str] = []
        self.order: list[int] = []
        self.colors: list[QtGui.QColor] = []

    def rowCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else len(self.order)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = self.order[index.row()]
        path = self.paths[row]
        if role == Qt.DisplayRole:
            return os.path.basename(path.split("::")[-1])
        if role == Qt.ToolTipRole:
            return path
        if role == Qt.DecorationRole:
            return self.owner.thumbnail(path)
        if role == ROW_ROLE:
            return row
        if role == COLOR_ROLE:
            return self.colors[row] if row < len(self.colors) else None
        return None


class ColorBarDelegate(QtWidgets.QStyledItemDelegate):
    def paint(self, painter, option, index):
        color = index.data(COLOR_ROLE)
        bar = dpix(COLOR_BAR)
        if color is not None:
            painter.fillRect(QtCore.QRect(option.rect.left(), option.rect.top(), bar, option.rect.height()), color)
        shifted = QtWidgets.QStyleOptionViewItem(option)
        shifted.rect = option.rect.adjusted(bar + dpix(2), 0, 0, 0)
        super().paint(painter, shifted, index)


class FileList(QtWidgets.QListView, ActionKit.UIMixin):
    selection_changed = QtCore.Signal()

    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self.owner = owner
        self.file_model = FileListModel(owner, self)
        self.positions: dict[int, int] = {}
        self.path_positions: dict[str, int] = {}
        self.syncing = False
        self.setModel(self.file_model)
        self.setItemDelegate(ColorBarDelegate(self))
        self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.setUniformItemSizes(True)
        self.setIconSize(QtCore.QSize(dpix(ICON_SIZE), dpix(ICON_SIZE)))
        self.init_command_binding("MappingView", use_existing_events=True)
        self.selectionModel().selectionChanged.connect(self.on_selection)

    def set_rows(self, paths: list[str], order: np.ndarray, colors: list[QtGui.QColor]):
        self.file_model.beginResetModel()
        self.file_model.paths = list(paths)
        self.file_model.order = [int(row) for row in order]
        self.file_model.colors = colors
        self.file_model.endResetModel()
        self.positions = {row: position for position, row in enumerate(self.file_model.order)}
        self.path_positions = {self.file_model.paths[row]: position for row, position in self.positions.items()}

    def clear_rows(self):
        self.set_rows([], np.zeros(0, dtype=np.int64), [])

    def selected_rows(self) -> list[int]:
        return sorted(self.file_model.order[index.row()] for index in self.selectionModel().selectedRows())

    def select_rows(self, rows: Iterable[int]):
        positions = sorted(self.positions[row] for row in rows if row in self.positions)
        selection = QtCore.QItemSelection()
        start = previous = None
        for position in [*positions, None]:
            if start is not None and position != previous + 1:
                selection.select(self.file_model.index(start, 0), self.file_model.index(previous, 0))
                start = None
            if position is not None and start is None:
                start = position
            previous = position
        self.syncing = True
        try:
            self.selectionModel().select(selection, QtCore.QItemSelectionModel.ClearAndSelect)
        finally:
            self.syncing = False

    def update_path(self, path: str):
        position = self.path_positions.get(path)
        if position is not None:
            index = self.file_model.index(position, 0)
            self.file_model.dataChanged.emit(index, index, [Qt.DecorationRole])

    def on_selection(self, *_):
        if not self.syncing:
            self.selection_changed.emit()

    def extend_context(self, ctx, cmd, event=None, key=None, source=None):
        return self.owner.context_for_selection()
