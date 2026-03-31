from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from .tree import LeafNode, Orientation, SplitNode


def build_splitter(
    node: SplitNode | LeafNode,
    widgets: dict[str, QtWidgets.QWidget],
    parent: QtWidgets.QWidget | None = None,
) -> QtWidgets.QSplitter | QtWidgets.QWidget | None:
    if isinstance(node, LeafNode):
        w = widgets.get(node.panel_name)
        if w is not None:
            w.setParent(parent)
            w.show()
        return w

    qt_orient = (
        QtCore.Qt.Horizontal
        if node.orientation == Orientation.HORIZONTAL
        else QtCore.Qt.Vertical
    )
    splitter = QtWidgets.QSplitter(qt_orient, parent)
    splitter.setChildrenCollapsible(True)
    splitter.setHandleWidth(6)

    for child in node.children:
        child_widget = build_splitter(child, widgets, splitter)
        if child_widget is not None:
            splitter.addWidget(child_widget)

    if node.sizes and len(node.sizes) == splitter.count():
        splitter.setSizes(node.sizes)

    return splitter


def snapshot_sizes(
    node: SplitNode | LeafNode,
    splitter_stack: list[QtWidgets.QSplitter],
    index: list[int],
) -> None:
    if isinstance(node, LeafNode):
        return
    if index[0] < len(splitter_stack):
        s = splitter_stack[index[0]]
        node.sizes = s.sizes()
        index[0] += 1
    for child in node.children:
        snapshot_sizes(child, splitter_stack, index)


def collect_splitters(widget: QtWidgets.QWidget) -> list[QtWidgets.QSplitter]:
    result = []
    if isinstance(widget, QtWidgets.QSplitter):
        result.append(widget)
        for i in range(widget.count()):
            result.extend(collect_splitters(widget.widget(i)))
    return result
