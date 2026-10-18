from __future__ import annotations

import os
from collections import OrderedDict
from collections.abc import Iterable

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from wafer.qt.commands.bridge import ActionKit
from wafer.qt.common.dpi import dpix

ROW_ROLE = Qt.UserRole + 1
COLOR_ROLE = Qt.UserRole + 2
ICON_SIZE = 40
ICON_CACHE = 2000
COLOR_BAR = 4


class FileListModel(QtCore.QAbstractListModel):
    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self.owner = owner
        self.paths: list[str] = []
        self.order = np.zeros(0, dtype=np.int64)
        self.colors: list[QtGui.QColor] = []
        self.selected = np.zeros(0, dtype=bool)
        self.icons: OrderedDict[str, tuple[int, QtGui.QPixmap]] = OrderedDict()
        self.pixel_ratio = 1.0

    def icon(self, path: str) -> QtGui.QPixmap | None:
        pixmap = self.owner.thumbnail(path)
        if pixmap is None or pixmap.isNull():
            return pixmap
        cached = self.icons.get(path)
        if cached is not None and cached[0] == pixmap.cacheKey():
            self.icons.move_to_end(path)
            return cached[1]
        side = round(dpix(ICON_SIZE) * self.pixel_ratio)
        icon = pixmap.scaled(side, side, Qt.KeepAspectRatio, Qt.SmoothTransformation) if max(pixmap.width(), pixmap.height()) > side else QtGui.QPixmap(pixmap)
        icon.setDevicePixelRatio(self.pixel_ratio)
        self.icons[path] = (pixmap.cacheKey(), icon)
        while len(self.icons) > ICON_CACHE:
            self.icons.popitem(last=False)
        return icon

    def rowCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else len(self.order)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row = int(self.order[index.row()])
        path = self.paths[row]
        if role == Qt.DisplayRole:
            return os.path.basename(path.split("::")[-1])
        if role == Qt.ToolTipRole:
            return path
        if role == Qt.DecorationRole:
            return self.icon(path)
        if role == ROW_ROLE:
            return row
        if role == COLOR_ROLE:
            return self.colors[row] if row < len(self.colors) else None
        return None


class ColorBarDelegate(QtWidgets.QStyledItemDelegate):
    def __init__(self, model: FileListModel, parent=None):
        super().__init__(parent)
        self.file_model = model

    def paint(self, painter, option, index):
        color = index.data(COLOR_ROLE)
        bar = dpix(COLOR_BAR)
        if color is not None:
            painter.fillRect(QtCore.QRect(option.rect.left(), option.rect.top(), bar, option.rect.height()), color)
        shifted = QtWidgets.QStyleOptionViewItem(option)
        shifted.rect = option.rect.adjusted(bar + dpix(2), 0, 0, 0)
        if self.file_model.selected[self.file_model.order[index.row()]]:
            shifted.state |= QtWidgets.QStyle.State_Selected
        else:
            shifted.state &= ~QtWidgets.QStyle.State_Selected
        super().paint(painter, shifted, index)


class FileList(QtWidgets.QListView, ActionKit.UIMixin):
    selection_changed = QtCore.Signal()

    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self.owner = owner
        self.file_model = FileListModel(owner, self)
        self.path_positions: dict[str, int] = {}
        self.anchor: int | None = None
        self.drag_base = np.zeros(0, dtype=bool)
        self.pointing = False
        self.setModel(self.file_model)
        self.setItemDelegate(ColorBarDelegate(self.file_model, self))
        self.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.setUniformItemSizes(True)
        self.setIconSize(QtCore.QSize(dpix(ICON_SIZE), dpix(ICON_SIZE)))
        self.init_command_binding("MappingView", use_existing_events=True)

    def set_rows(self, paths: list[str], order: np.ndarray, colors: list[QtGui.QColor]):
        model = self.file_model
        model.beginResetModel()
        model.paths = list(paths)
        model.order = np.asarray(order, dtype=np.int64).reshape(-1)
        model.colors = colors
        model.selected = np.zeros(len(model.paths), dtype=bool)
        model.icons.clear()
        model.pixel_ratio = self.devicePixelRatioF()
        model.endResetModel()
        self.path_positions = {model.paths[row]: position for position, row in enumerate(model.order.tolist())}
        self.anchor = None

    def set_groups(self, order: np.ndarray, colors: list[QtGui.QColor]) -> None:
        model = self.file_model
        model.layoutAboutToBeChanged.emit()
        model.order = np.asarray(order, dtype=np.int64).reshape(-1)
        model.colors = colors
        model.layoutChanged.emit()
        self.path_positions = {model.paths[row]: position for position, row in enumerate(model.order.tolist())}

    def clear_rows(self):
        self.set_rows([], np.zeros(0, dtype=np.int64), [])

    def selected_rows(self) -> list[int]:
        return np.flatnonzero(self.file_model.selected).tolist()

    def select_rows(self, rows: Iterable[int]):
        wanted = np.fromiter(rows, dtype=np.int64)
        mask = np.zeros(len(self.file_model.paths), dtype=bool)
        mask[wanted[(wanted >= 0) & (wanted < mask.size)]] = True
        self.set_selection(mask)

    def set_selection(self, mask: np.ndarray) -> None:
        self.file_model.selected = mask
        self.viewport().update()

    def apply_selection(self, mask: np.ndarray) -> None:
        if np.array_equal(mask, self.file_model.selected):
            return
        self.set_selection(mask)
        self.selection_changed.emit()

    def span(self, start: int, end: int) -> np.ndarray:
        low, high = sorted((start, end))
        mask = np.zeros(len(self.file_model.paths), dtype=bool)
        mask[self.file_model.order[low : high + 1]] = True
        return mask

    def mousePressEvent(self, event: QtGui.QMouseEvent):
        index = self.indexAt(event.position().toPoint())
        if event.button() in (Qt.LeftButton, Qt.RightButton):
            self.press(index, event.button(), event.modifiers())
        self.pass_pointer(super().mousePressEvent, event)

    def pass_pointer(self, handler, event: QtGui.QMouseEvent) -> None:
        self.pointing = True
        try:
            handler(event)
        finally:
            self.pointing = False

    def press(self, index: QtCore.QModelIndex, button: Qt.MouseButton, modifiers: Qt.KeyboardModifier) -> None:
        selected = self.file_model.selected
        if not index.isValid():
            self.drag_base = np.zeros(0, dtype=bool)
            if button == Qt.LeftButton and not modifiers & (Qt.ControlModifier | Qt.ShiftModifier):
                self.apply_selection(np.zeros_like(selected))
            return
        position = index.row()
        row = int(self.file_model.order[position])
        if button == Qt.RightButton:
            self.drag_base = np.zeros(0, dtype=bool)
            if not selected[row]:
                self.anchor = position
                self.apply_selection(self.span(position, position))
            return
        if modifiers & Qt.ShiftModifier and self.anchor is not None:
            base = selected.copy() if modifiers & Qt.ControlModifier else np.zeros_like(selected)
            self.apply_selection(base | self.span(self.anchor, position))
        elif modifiers & Qt.ControlModifier:
            mask = selected.copy()
            mask[row] = not mask[row]
            self.anchor = position
            self.apply_selection(mask)
        else:
            self.anchor = position
            self.apply_selection(self.span(position, position))
        self.drag_base = selected.copy() if modifiers & Qt.ControlModifier else np.zeros_like(selected)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent):
        if event.buttons() & Qt.LeftButton and self.anchor is not None and self.drag_base.size == len(self.file_model.paths):
            index = self.indexAt(event.position().toPoint())
            if index.isValid():
                self.apply_selection(self.drag_base | self.span(self.anchor, index.row()))
        self.pass_pointer(super().mouseMoveEvent, event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent):
        self.pass_pointer(super().mouseReleaseEvent, event)

    def currentChanged(self, current: QtCore.QModelIndex, previous: QtCore.QModelIndex):
        super().currentChanged(current, previous)
        if self.pointing or not current.isValid():
            return
        modifiers = QtWidgets.QApplication.keyboardModifiers()
        position = current.row()
        if modifiers & Qt.ShiftModifier and self.anchor is not None:
            self.apply_selection(self.span(self.anchor, position))
        elif not modifiers & Qt.ControlModifier:
            self.anchor = position
            self.apply_selection(self.span(position, position))

    def update_path(self, path: str):
        position = self.path_positions.get(path)
        if position is not None:
            index = self.file_model.index(position, 0)
            self.file_model.dataChanged.emit(index, index, [Qt.DecorationRole])

    def extend_context(self, ctx, cmd, event=None, key=None, source=None):
        return self.owner.context_for_selection()
