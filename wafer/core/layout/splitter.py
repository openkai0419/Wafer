from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from ...utils.formatting import dpix
from .tree import LeafNode, SplitNode

HANDLE_WIDTH = 6
GRIP_DOT_COUNT = 7
GRIP_DOT_RADIUS = 1
GRIP_DOT_SPACING = 5


class GripHandle(QtWidgets.QSplitterHandle):
    def paintEvent(self, event):
        from ...core.color.theme import ThemeManager
        p = ThemeManager.instance().palette
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        color = QtGui.QColor(p.border_subtle)
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(color)
        r = dpix(GRIP_DOT_RADIUS)
        spacing = dpix(GRIP_DOT_SPACING)
        cx = self.width() / 2
        cy = self.height() / 2
        horizontal = self.orientation() == QtCore.Qt.Horizontal
        total = (GRIP_DOT_COUNT - 1) * spacing
        for i in range(GRIP_DOT_COUNT):
            offset = -total / 2 + i * spacing
            if horizontal:
                painter.drawEllipse(QtCore.QPointF(cx, cy + offset), r, r)
            else:
                painter.drawEllipse(QtCore.QPointF(cx + offset, cy), r, r)
        painter.end()


class GripSplitter(QtWidgets.QSplitter):
    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self.setChildrenCollapsible(True)
        self.setHandleWidth(dpix(HANDLE_WIDTH))

    def createHandle(self):
        return GripHandle(self.orientation(), self)


def build_splitter(
    node: SplitNode | LeafNode,
    widgets: dict[str, QtWidgets.QWidget],
    parent: QtWidgets.QWidget | None = None,
    collapsed: set[str] | None = None,
) -> QtWidgets.QSplitter | QtWidgets.QWidget | None:
    if isinstance(node, LeafNode):
        w = widgets.get(node.panel_name)
        if w is not None:
            if collapsed and node.panel_name in collapsed:
                w.hide()
            w.setParent(parent)
        return w

    splitter = GripSplitter(node.orientation.to_qt(), parent)

    visible_sizes = []
    for i, child in enumerate(node.children):
        child_widget = build_splitter(child, widgets, splitter, collapsed)
        if child_widget is not None:
            splitter.addWidget(child_widget)
            if i < len(node.sizes):
                visible_sizes.append(node.sizes[i])

    if visible_sizes and len(visible_sizes) == splitter.count():
        splitter.setSizes(visible_sizes)

    return splitter


def snapshot_sizes(
    node: SplitNode | LeafNode,
    splitter_stack: list[QtWidgets.QSplitter],
    index: list[int],
) -> None:
    it = iter(splitter_stack[index[0]:])
    _snapshot_sizes_iter(node, it)
    index[0] = len(splitter_stack) - sum(1 for _ in it)


def _snapshot_sizes_iter(
    node: SplitNode | LeafNode,
    it: iter,
) -> None:
    if isinstance(node, LeafNode):
        return
    splitter = next(it, None)
    if splitter is not None:
        node.sizes = list(splitter.sizes())
    for child in node.children:
        _snapshot_sizes_iter(child, it)


def collect_splitters(widget: QtWidgets.QWidget) -> list[QtWidgets.QSplitter]:
    result: list[QtWidgets.QSplitter] = []
    stack = [widget]
    while stack:
        w = stack.pop()
        if isinstance(w, QtWidgets.QSplitter):
            result.append(w)
            for i in range(w.count() - 1, -1, -1):
                stack.append(w.widget(i))
    return result
