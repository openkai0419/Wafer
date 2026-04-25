from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from ...plugin import BaseTagPanelPlugin
from ...ui.panel.meta_viewer import CollapsibleCard
from ...utils.formatting import dpix
from .registry import MarkRegistry


class _MarkBadgeRow(QtWidgets.QWidget):
    def __init__(self, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent)
        self._active_ids: list[str] = []
        self.setMinimumHeight(dpix(28))
        MarkRegistry.instance().changed.connect(self.update)

    def set_ids(self, ids: list[str]):
        self._active_ids = list(ids)
        self.update()

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        registry = MarkRegistry.instance()
        all_ids = registry.ids()
        if not all_ids:
            return
        active = set(self._active_ids)
        diameter = dpix(20)
        gap = dpix(6)
        x = dpix(4)
        y = max(0, (self.height() - diameter) // 2)
        for mid in all_ids:
            color = registry.qcolor_for(mid)
            if mid in active:
                painter.setBrush(color)
                pen = QtGui.QPen(QtGui.QColor(0, 0, 0, 180), max(1, dpix(1)))
            else:
                fade = QtGui.QColor(color)
                fade.setAlpha(40)
                painter.setBrush(fade)
                pen = QtGui.QPen(QtGui.QColor(0, 0, 0, 60), max(1, dpix(1)))
            painter.setPen(pen)
            painter.drawEllipse(x, y, diameter, diameter)
            if mid in active:
                painter.save()
                painter.setPen(QtGui.QColor(0, 0, 0, 220))
                f = painter.font()
                f.setBold(True)
                painter.setFont(f)
                painter.drawText(QtCore.QRect(x, y, diameter, diameter), QtCore.Qt.AlignCenter, mid)
                painter.restore()
            x += diameter + gap


class MarkTagPanelPlugin(BaseTagPanelPlugin):
    NAME = "mark_panel"
    PREFIX = "mark"
    DEFAULT_ENABLED = True
    PRIORITY = 50

    def __init__(self):
        self._card: CollapsibleCard | None = None
        self._row: _MarkBadgeRow | None = None

    def create_card(self, parent: QtWidgets.QWidget | None = None) -> QtWidgets.QWidget:
        self._card = CollapsibleCard(self.PREFIX, f"tag:{self.PREFIX}", parent)
        self._row = _MarkBadgeRow(self._card)
        self._card.set_content_widget(self._row)
        return self._card

    def update_data(
        self,
        tags: dict[str, str],
        locks: dict[str, bool],
        path: str,
        file_hash: str,
        db: str,
    ) -> None:
        ids = sorted((str(k) for k in (tags or {})), key=lambda x: (len(x), x))
        if self._row is not None:
            self._row.set_ids(ids)
        if self._card is not None:
            self._card.update_title_count(len(ids))
