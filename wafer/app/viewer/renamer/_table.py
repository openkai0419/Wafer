from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from ....utils.formatting import dpix


class PreviewDelegate(QtWidgets.QStyledItemDelegate):

    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self._pen = QtGui.QPen(QtGui.QColor(color), dpix(1))

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        if index.column() == 0:
            painter.save()
            painter.setPen(self._pen)
            x = option.rect.right()
            painter.drawLine(x, option.rect.top(), x, option.rect.bottom())
            painter.restore()


class SyncedTable(QtWidgets.QTableWidget):

    def __init__(self, forward_target=None, parent=None):
        super().__init__(parent)
        self._fwd = forward_target

    def set_forward_target(self, target):
        self._fwd = target

    def wheelEvent(self, event):
        if self._fwd:
            sb = self._fwd.verticalScrollBar()
            delta = event.angleDelta().y()
            sb.setValue(sb.value() - delta // 3)
            event.accept()
        else:
            super().wheelEvent(event)
