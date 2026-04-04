from __future__ import annotations

from PySide6 import QtWidgets

from .tree import LeafNode, SplitNode


def build_splitter(
    node: SplitNode | LeafNode,
    widgets: dict[str, QtWidgets.QWidget],
    parent: QtWidgets.QWidget | None = None,
) -> QtWidgets.QSplitter | QtWidgets.QWidget | None:
    if isinstance(node, LeafNode):
        w = widgets.get(node.panel_name)
        if w is not None:
            w.setParent(parent)
        return w

    splitter = QtWidgets.QSplitter(node.orientation.to_qt(), parent)
    splitter.setChildrenCollapsible(True)
    splitter.setHandleWidth(6)

    visible_sizes = []
    for i, child in enumerate(node.children):
        child_widget = build_splitter(child, widgets, splitter)
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
    if isinstance(node, LeafNode):
        return
    if index[0] < len(splitter_stack):
        s = splitter_stack[index[0]]
        node.sizes = list(s.sizes())
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
