from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

if TYPE_CHECKING:
    from ._dialog import BatchRenameDialog


class ThumbnailOverlay(QtWidgets.QWidget):

    def __init__(
        self, dialog: BatchRenameDialog, table: QtWidgets.QTableView, parent=None,
    ):
        super().__init__(parent)
        self._dlg = dialog
        self._tbl = table
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAutoFillBackground(False)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        tbl = self._tbl
        header = tbl.horizontalHeader()
        vp = tbl.viewport()
        vp_h = vp.height()

        col0_x = header.sectionPosition(0) - header.offset()
        col0_w = header.sectionSize(0)
        col1_x = header.sectionPosition(1) - header.offset()
        col1_w = header.sectionSize(1)

        first = tbl.indexAt(vp.rect().topLeft()).row()
        last = tbl.indexAt(vp.rect().bottomLeft()).row()
        if first < 0:
            first = 0
        if last < 0:
            last = tbl.model().rowCount() - 1

        painter.setOpacity(0.2)
        for row in range(first, last + 1):
            pix = self._dlg._thumb_for_row(row)
            if not pix or pix.isNull():
                continue
            rect = tbl.visualRect(tbl.model().index(row, 0))
            cell = QtCore.QRect(col0_x, rect.y(), col0_w, rect.height())
            self._draw_cover(painter, pix, cell)

        sel = self._dlg._selected_row
        pix = self._dlg._thumb_for_row(sel) if sel >= 0 else None
        if pix and not pix.isNull():
            painter.setOpacity(0.12)
            full = QtCore.QRect(col1_x, 0, col1_w, vp_h)
            self._draw_cover(painter, pix, full)

        painter.end()

    @staticmethod
    def _draw_cover(painter: QtGui.QPainter, pix: QtGui.QPixmap, rect: QtCore.QRect):
        pw, ph = pix.width(), pix.height()
        rw, rh = rect.width(), rect.height()
        if pw <= 0 or ph <= 0 or rw <= 0 or rh <= 0:
            return
        scale = max(rw / pw, rh / ph)
        sw = int(pw * scale)
        sh = int(ph * scale)
        dx = rect.x() + (rw - sw) // 2
        dy = rect.y() + (rh - sh) // 2
        painter.save()
        painter.setClipRect(rect)
        painter.drawPixmap(dx, dy, sw, sh, pix)
        painter.restore()
