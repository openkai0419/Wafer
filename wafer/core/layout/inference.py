from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from .tree import FloatingState, LeafNode, Orientation, SplitNode
from .dock import capture_floating_state


def infer_tree(
    panels: dict[str, QtWidgets.QDockWidget],
    window: QtWidgets.QMainWindow,
) -> tuple[SplitNode | LeafNode | None, dict[str, FloatingState]]:
    docked: list[tuple[str, QtCore.QRect]] = []
    floating: dict[str, FloatingState] = {}

    for name, dock in panels.items():
        if not dock.isVisible():
            continue
        if dock.isFloating():
            floating[name] = capture_floating_state(dock)
        else:
            geo = dock.geometry()
            docked.append((name, geo))

    if not docked:
        return None, floating

    root = _bisect(docked)
    return root, floating


def _bisect(items: list[tuple[str, QtCore.QRect]]) -> SplitNode | LeafNode:
    if len(items) == 1:
        return LeafNode(items[0][0])

    best_orient = Orientation.HORIZONTAL
    best_groups = None
    best_score = -1.0

    for orient in (Orientation.HORIZONTAL, Orientation.VERTICAL):
        groups = _find_split(items, orient)
        if groups is None:
            continue
        score = _split_quality(groups, orient)
        if score > best_score:
            best_score = score
            best_orient = orient
            best_groups = groups

    if best_groups is None:
        best_groups = _force_split(items, best_orient)

    children = [_bisect(g) for g in best_groups]
    sizes = [_group_extent(g, best_orient) for g in best_groups]
    return SplitNode(orientation=best_orient, children=children, sizes=sizes)


def _find_split(
    items: list[tuple[str, QtCore.QRect]],
    orient: Orientation,
) -> list[list[tuple[str, QtCore.QRect]]] | None:
    if orient == Orientation.HORIZONTAL:
        key_start = lambda r: r.left()
        key_end = lambda r: r.right()
        key_center = lambda r: r.center().x()
    else:
        key_start = lambda r: r.top()
        key_end = lambda r: r.bottom()
        key_center = lambda r: r.center().y()

    sorted_items = sorted(items, key=lambda t: key_center(t[1]))

    best_gap = -1
    best_pos = -1
    for i in range(1, len(sorted_items)):
        gap = key_start(sorted_items[i][1]) - key_end(sorted_items[i - 1][1])
        if gap > best_gap:
            best_gap = gap
            best_pos = i

    if best_pos < 1:
        return None

    return [sorted_items[:best_pos], sorted_items[best_pos:]]


def _force_split(
    items: list[tuple[str, QtCore.QRect]],
    orient: Orientation,
) -> list[list[tuple[str, QtCore.QRect]]]:
    if orient == Orientation.HORIZONTAL:
        key_center = lambda r: r.center().x()
    else:
        key_center = lambda r: r.center().y()

    sorted_items = sorted(items, key=lambda t: key_center(t[1]))
    mid = len(sorted_items) // 2
    return [sorted_items[:mid], sorted_items[mid:]]


def _split_quality(
    groups: list[list[tuple[str, QtCore.QRect]]],
    orient: Orientation,
) -> float:
    if len(groups) != 2:
        return 0.0

    if orient == Orientation.HORIZONTAL:
        end_a = max(r.right() for _, r in groups[0])
        start_b = min(r.left() for _, r in groups[1])
    else:
        end_a = max(r.bottom() for _, r in groups[0])
        start_b = min(r.top() for _, r in groups[1])

    gap = start_b - end_a
    return float(gap)


def _group_extent(
    group: list[tuple[str, QtCore.QRect]],
    orient: Orientation,
) -> int:
    if orient == Orientation.HORIZONTAL:
        return max(r.right() for _, r in group) - min(r.left() for _, r in group)
    return max(r.bottom() for _, r in group) - min(r.top() for _, r in group)
