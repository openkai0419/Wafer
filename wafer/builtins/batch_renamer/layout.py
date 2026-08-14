from __future__ import annotations

from PySide6 import QtWidgets
from PySide6.QtCore import Qt

from ...ui.layout.splitter import HANDLE_WIDTH, GripHandle
from ...utils.formatting import dpix

DIRECTIONS = ("TB", "BT", "LR", "RL")
DIRECTION_ICONS = {"TB": "layout_tb", "BT": "layout_bt", "LR": "layout_lr", "RL": "layout_rl"}

_VERTICAL = {"TB", "BT"}
_REVERSED = {"BT", "RL"}


def normalise_direction(direction: str, default: str = "TB") -> str:
    return direction if direction in DIRECTIONS else default


class OrientedSplitter(QtWidgets.QSplitter):
    """Two-pane splitter whose orientation and pane order follow a 4-way direction.

    The first pane is the logical primary (preview / original); the second is the
    secondary (edit / result). ``direction`` is one of TB/BT/LR/RL where the first
    letter is the primary pane's position (Top/Bottom/Left/Right).
    """

    def __init__(self, first: QtWidgets.QWidget, second: QtWidgets.QWidget, direction: str = "TB", parent=None):
        super().__init__(parent)
        self.setChildrenCollapsible(False)
        self.setHandleWidth(dpix(HANDLE_WIDTH))
        self._first = first
        self._second = second
        self._pending_sizes: list[int] | None = None
        self._direction = normalise_direction(direction)
        self.addWidget(first)
        self.addWidget(second)
        self.set_direction(self._direction)

    def createHandle(self):
        return GripHandle(self.orientation(), self)

    @property
    def direction(self) -> str:
        return self._direction

    def set_direction(self, direction: str):
        self._direction = normalise_direction(direction, self._direction)
        self.setOrientation(Qt.Vertical if self._direction in _VERTICAL else Qt.Horizontal)
        lead, trail = (self._second, self._first) if self._direction in _REVERSED else (self._first, self._second)
        if self.widget(0) is not lead:
            self.insertWidget(0, lead)
        if self.widget(1) is not trail:
            self.insertWidget(1, trail)

    def ordered_sizes(self) -> list[int]:
        """Sizes in logical (first, second) order, independent of visual reversal."""
        sizes = self.sizes()
        return sizes[::-1] if self._direction in _REVERSED else sizes

    def apply_ordered_sizes(self, sizes: list[int]):
        if not sizes or len(sizes) != 2:
            return
        visual = sizes[::-1] if self._direction in _REVERSED else list(sizes)
        if sum(self.sizes()) > 0:
            self.setSizes(visual)
            self._pending_sizes = None
        else:
            self._pending_sizes = visual

    def showEvent(self, event):
        super().showEvent(event)
        if self._pending_sizes and sum(self.sizes()) > 0:
            self.setSizes(self._pending_sizes)
            self._pending_sizes = None

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._pending_sizes and sum(self.sizes()) > 0:
            self.setSizes(self._pending_sizes)
            self._pending_sizes = None
