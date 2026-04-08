from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto


class Orientation(Enum):
    HORIZONTAL = auto()
    VERTICAL = auto()

    def to_qt(self):
        from PySide6 import QtCore

        return QtCore.Qt.Horizontal if self == Orientation.HORIZONTAL else QtCore.Qt.Vertical


@dataclass
class LeafNode:
    panel_name: str


@dataclass
class SplitNode:
    orientation: Orientation
    children: list[LeafNode | SplitNode]
    sizes: list[int] = field(default_factory=list)

    def panel_names(self) -> list[str]:
        result = []
        for child in self.children:
            if isinstance(child, LeafNode):
                result.append(child.panel_name)
            else:
                result.extend(child.panel_names())
        return result


@dataclass
class FloatingState:
    x: int
    y: int
    width: int
    height: int


@dataclass
class LayoutTree:
    root: SplitNode | LeafNode | None = None
    floating: dict[str, FloatingState] = field(default_factory=dict)
    collapsed: set[str] = field(default_factory=set)

    def docked_names(self) -> list[str]:
        if self.root is None:
            return []
        if isinstance(self.root, LeafNode):
            return [self.root.panel_name]
        return self.root.panel_names()

    def all_names(self) -> set[str]:
        return set(self.docked_names()) | set(self.floating.keys())

    def to_dict(self) -> dict:
        return {
            "root": _node_to_dict(self.root),
            "floating": {k: {"x": v.x, "y": v.y, "width": v.width, "height": v.height} for k, v in self.floating.items()},
            "collapsed": sorted(self.collapsed),
        }

    @classmethod
    def from_dict(cls, data: dict) -> LayoutTree:
        root = _node_from_dict(data.get("root"))
        floating = {}
        for k, v in data.get("floating", {}).items():
            floating[k] = FloatingState(v["x"], v["y"], v["width"], v["height"])
        collapsed = set(data.get("collapsed", []))
        return cls(root=root, floating=floating, collapsed=collapsed)


def _node_to_dict(node) -> dict | None:
    if node is None:
        return None
    if isinstance(node, LeafNode):
        return {"type": "leaf", "panel": node.panel_name}
    return {
        "type": "split",
        "orientation": node.orientation.name.lower(),
        "sizes": node.sizes,
        "children": [_node_to_dict(c) for c in node.children],
    }


def _node_from_dict(data) -> SplitNode | LeafNode | None:
    if data is None:
        return None
    if data["type"] == "leaf":
        return LeafNode(data["panel"])
    orientation = Orientation[data["orientation"].upper()]
    children = [_node_from_dict(c) for c in data.get("children", [])]
    return SplitNode(
        orientation=orientation,
        children=children,
        sizes=data.get("sizes", []),
    )


def remove_panel(node: SplitNode | LeafNode | None, name: str) -> SplitNode | LeafNode | None:
    if node is None:
        return None
    if isinstance(node, LeafNode):
        return None if node.panel_name == name else node
    new_children = []
    new_sizes = []
    for i, child in enumerate(node.children):
        result = remove_panel(child, name)
        if result is not None:
            new_children.append(result)
            if i < len(node.sizes):
                new_sizes.append(node.sizes[i])
    if not new_children:
        return None
    if len(new_children) == 1:
        return new_children[0]
    return SplitNode(
        orientation=node.orientation,
        children=new_children,
        sizes=new_sizes,
    )


def insert_panel(
    node: SplitNode | LeafNode | None,
    name: str,
    orientation: Orientation = Orientation.HORIZONTAL,
    position: int = -1,
) -> SplitNode | LeafNode:
    leaf = LeafNode(name)
    if node is None:
        return leaf
    if isinstance(node, LeafNode):
        children = [node, leaf] if position == -1 else [leaf, node]
        return SplitNode(orientation=orientation, children=children)
    if node.orientation == orientation:
        idx = len(node.children) if position == -1 else max(0, min(position, len(node.children)))
        new_children = list(node.children)
        new_children.insert(idx, leaf)
        new_sizes = list(node.sizes)
        avg = max(1, sum(new_sizes) // len(new_sizes)) if new_sizes else 100
        new_sizes.insert(idx, avg)
        return SplitNode(orientation=orientation, children=new_children, sizes=new_sizes)
    children = [node, leaf] if position == -1 else [leaf, node]
    return SplitNode(orientation=orientation, children=children)


def flatten(node: SplitNode | LeafNode | None) -> SplitNode | LeafNode | None:
    if node is None or isinstance(node, LeafNode):
        return node
    new_children: list[LeafNode | SplitNode] = []
    new_sizes: list[int] = []
    for i, child in enumerate(node.children):
        size = node.sizes[i] if i < len(node.sizes) else 1
        child = flatten(child)
        if isinstance(child, SplitNode) and child.orientation == node.orientation:
            child_total = sum(child.sizes) if child.sizes else 1
            child_sizes = child.sizes if child.sizes else [1] * len(child.children)
            for gc, gs in zip(child.children, child_sizes):
                new_children.append(gc)
                new_sizes.append(int(size * gs / child_total) if child_total else size)
        else:
            new_children.append(child)
            new_sizes.append(size)
    if len(new_children) == 1:
        return new_children[0]
    return SplitNode(orientation=node.orientation, children=new_children, sizes=new_sizes)


def _find_parent_context(
    node: SplitNode | LeafNode | None,
    name: str,
) -> tuple[SplitNode, int] | None:
    if node is None or isinstance(node, LeafNode):
        return None
    for i, child in enumerate(node.children):
        if isinstance(child, LeafNode) and child.panel_name == name:
            return (node, i)
        result = _find_parent_context(child, name)
        if result is not None:
            return result
    return None


def _collect_names(node: SplitNode | LeafNode | None) -> set[str]:
    if node is None:
        return set()
    if isinstance(node, LeafNode):
        return {node.panel_name}
    result: set[str] = set()
    for c in node.children:
        result |= _collect_names(c)
    return result


DEFAULT_RESTORE_SIZE = 200


def normalize_sizes(
    node: SplitNode | LeafNode | None,
    collapsed: set[str],
) -> bool:
    if node is None:
        return False
    if isinstance(node, LeafNode):
        return node.panel_name not in collapsed

    has_visible = False
    non_zero_sizes = [s for s in node.sizes if s > 0]
    fallback = (sum(non_zero_sizes) // len(non_zero_sizes)) if non_zero_sizes else DEFAULT_RESTORE_SIZE

    for i, child in enumerate(node.children):
        child_visible = normalize_sizes(child, collapsed)
        if child_visible and i < len(node.sizes) and node.sizes[i] <= 0:
            node.sizes[i] = fallback
        has_visible = has_visible or child_visible
    return has_visible


def reinsert_from_blueprint(
    current: SplitNode | LeafNode | None,
    blueprint: SplitNode | LeafNode | None,
    name: str,
) -> SplitNode | LeafNode:
    leaf = LeafNode(name)
    if blueprint is None:
        return insert_panel(current, name)

    ctx = _find_parent_context(blueprint, name)
    if ctx is None:
        return insert_panel(current, name)

    parent_node, idx = ctx
    bp_size = parent_node.sizes[idx] if idx < len(parent_node.sizes) else 200

    existing = _collect_names(current)
    sibling_names = []
    for i, child in enumerate(parent_node.children):
        if i != idx:
            if isinstance(child, LeafNode):
                sibling_names.append((i, child.panel_name))
            else:
                for pn in child.panel_names():
                    sibling_names.append((i, pn))

    anchor: str | None = None
    anchor_after = True
    best_before: tuple[int, str] | None = None
    best_after_item: tuple[int, str] | None = None
    for si, sn in sibling_names:
        if sn not in existing:
            continue
        if si < idx:
            best_before = (si, sn)
        elif best_after_item is None:
            best_after_item = (si, sn)

    if best_before is not None:
        anchor = best_before[1]
        anchor_after = True
    elif best_after_item is not None:
        anchor = best_after_item[1]
        anchor_after = False

    if current is None:
        return leaf

    if anchor is None:
        return insert_panel(current, name, parent_node.orientation)

    return _insert_near(current, leaf, anchor, anchor_after, parent_node.orientation, bp_size)


def _insert_near(
    node: SplitNode | LeafNode | None,
    leaf: LeafNode,
    anchor: str,
    after: bool,
    orientation: Orientation,
    size: int,
) -> SplitNode | LeafNode:
    if node is None:
        return leaf

    if isinstance(node, LeafNode):
        if node.panel_name == anchor:
            children = [node, leaf] if after else [leaf, node]
            sizes = [200, size] if after else [size, 200]
            return SplitNode(orientation=orientation, children=children, sizes=sizes)
        return node

    for i, child in enumerate(node.children):
        if isinstance(child, LeafNode) and child.panel_name == anchor:
            if node.orientation == orientation:
                new_children = list(node.children)
                new_sizes = list(node.sizes)
                insert_idx = i + 1 if after else i
                new_children.insert(insert_idx, leaf)
                new_sizes.insert(insert_idx, size)
                return SplitNode(orientation=node.orientation, children=new_children, sizes=new_sizes)
            else:
                children = [child, leaf] if after else [leaf, child]
                child_size = node.sizes[i] if i < len(node.sizes) else 200
                sizes = [child_size, size] if after else [size, child_size]
                wrapper = SplitNode(orientation=orientation, children=children, sizes=sizes)
                new_node_children = list(node.children)
                new_node_children[i] = wrapper
                return SplitNode(orientation=node.orientation, children=new_node_children, sizes=list(node.sizes))
        if isinstance(child, SplitNode) and anchor in _collect_names(child):
            if node.orientation == orientation:
                new_children = list(node.children)
                new_sizes = list(node.sizes)
                insert_idx = i + 1 if after else i
                new_children.insert(insert_idx, leaf)
                new_sizes.insert(insert_idx, size)
                return SplitNode(orientation=node.orientation, children=new_children, sizes=new_sizes)
            new_child = _insert_near(child, leaf, anchor, after, orientation, size)
            new_children = list(node.children)
            new_children[i] = new_child
            return SplitNode(orientation=node.orientation, children=new_children, sizes=list(node.sizes))
