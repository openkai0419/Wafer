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


def _subtree_all_hidden(
    node: SplitNode | LeafNode,
    hidden: set[str],
) -> bool:
    if isinstance(node, LeafNode):
        return node.panel_name in hidden
    return all(_subtree_all_hidden(c, hidden) for c in node.children)


def snapshot_sizes(
    node: SplitNode | LeafNode,
    splitter_stack: list[QtWidgets.QSplitter],
    index: list[int],
    hidden: set[str] | frozenset[str] = frozenset(),
) -> None:
    if isinstance(node, LeafNode):
        return
    if index[0] < len(splitter_stack):
        s = splitter_stack[index[0]]
        splitter_sizes = s.sizes()
        new_sizes: list[int] = []
        si = 0
        for i, child in enumerate(node.children):
            if _subtree_all_hidden(child, hidden):
                new_sizes.append(node.sizes[i] if i < len(node.sizes) else 0)
            else:
                new_sizes.append(splitter_sizes[si] if si < len(splitter_sizes) else 0)
                si += 1
        node.sizes = new_sizes
        index[0] += 1
    for child in node.children:
        if not _subtree_all_hidden(child, hidden):
            snapshot_sizes(child, splitter_stack, index, hidden)


def collect_splitters(widget: QtWidgets.QWidget) -> list[QtWidgets.QSplitter]:
    result = []
    if isinstance(widget, QtWidgets.QSplitter):
        result.append(widget)
        for i in range(widget.count()):
            result.extend(collect_splitters(widget.widget(i)))
    return result
