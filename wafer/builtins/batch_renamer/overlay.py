from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

if TYPE_CHECKING:
    from .widget import BatchRenameWidget


class ThumbnailOverlay(QtWidgets.QWidget):
    FIT_COVER = "cover"
    FIT_CONTAIN = "contain"
    FIT_MODES = {FIT_COVER, FIT_CONTAIN}

    def __init__(
        self,
        dialog: BatchRenameWidget,
        table: QtWidgets.QTableView,
        parent=None,
    ):
        super().__init__(parent)
        self._dlg = dialog
        self._tbl = table
        self._row_opacity = 0.2
        self._sel_opacity = 0.2
        self._row_fit_mode = self.FIT_COVER
        self._sel_fit_mode = self.FIT_COVER
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAutoFillBackground(False)

    def set_row_opacity(self, value: float):
        self._row_opacity = value
        self.update()

    def set_sel_opacity(self, value: float):
        self._sel_opacity = value
        self.update()

    @property
    def row_fit_mode(self) -> str:
        return self._row_fit_mode

    @property
    def sel_fit_mode(self) -> str:
        return self._sel_fit_mode

    def set_row_fit_mode(self, fit_mode: str):
        self._row_fit_mode = self.normalise_fit_mode(fit_mode)
        self.update()

    def set_sel_fit_mode(self, fit_mode: str):
        self._sel_fit_mode = self.normalise_fit_mode(fit_mode)
        self.update()

    @classmethod
    def normalise_fit_mode(cls, fit_mode: str) -> str:
        return fit_mode if fit_mode in cls.FIT_MODES else cls.FIT_COVER

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

        painter.setOpacity(self._row_opacity)
        for row in range(first, last + 1):
            pix = self._dlg.thumb_for_row(row)
            if not pix or pix.isNull():
                continue
            rect = tbl.visualRect(tbl.model().index(row, 0))
            cell = QtCore.QRect(col0_x, rect.y(), col0_w, rect.height())
            self._draw_fit(painter, pix, cell, self._row_fit_mode)

        sel = self._dlg.selected_row
        pix = self._dlg.thumb_for_row(sel) if sel >= 0 else None
        if pix and not pix.isNull():
            painter.setOpacity(self._sel_opacity)
            full = QtCore.QRect(col1_x, 0, col1_w, vp_h)
            self._draw_fit(painter, pix, full, self._sel_fit_mode)

        painter.end()

    @staticmethod
    def _scaled_rect(pix: QtGui.QPixmap, rect: QtCore.QRect, fit_mode: str):
        pw, ph = pix.width(), pix.height()
        rw, rh = rect.width(), rect.height()
        if pw <= 0 or ph <= 0 or rw <= 0 or rh <= 0:
            return QtCore.QRect()
        scale = min(rw / pw, rh / ph) if fit_mode == ThumbnailOverlay.FIT_CONTAIN else max(rw / pw, rh / ph)
        sw = int(pw * scale)
        sh = int(ph * scale)
        dx = rect.x() + (rw - sw) // 2
        dy = rect.y() + (rh - sh) // 2
        return QtCore.QRect(dx, dy, sw, sh)

    @staticmethod
    def _draw_fit(painter: QtGui.QPainter, pix: QtGui.QPixmap, rect: QtCore.QRect, fit_mode: str):
        target = ThumbnailOverlay._scaled_rect(pix, rect, fit_mode)
        if target.isNull():
            return
        painter.save()
        painter.setClipRect(rect)
        painter.drawPixmap(target, pix)
        painter.restore()
