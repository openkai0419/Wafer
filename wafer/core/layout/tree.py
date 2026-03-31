from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto


class Orientation(Enum):
    HORIZONTAL = auto()
    VERTICAL = auto()


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
    hidden: set[str] = field(default_factory=set)

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
            'root': _node_to_dict(self.root),
            'floating': {
                k: {'x': v.x, 'y': v.y, 'width': v.width, 'height': v.height}
                for k, v in self.floating.items()
            },
            'hidden': list(self.hidden),
        }

    @classmethod
    def from_dict(cls, data: dict) -> LayoutTree:
        root = _node_from_dict(data.get('root'))
        floating = {}
        for k, v in data.get('floating', {}).items():
            floating[k] = FloatingState(v['x'], v['y'], v['width'], v['height'])
        hidden = set(data.get('hidden', []))
        return cls(root=root, floating=floating, hidden=hidden)


def _node_to_dict(node) -> dict | None:
    if node is None:
        return None
    if isinstance(node, LeafNode):
        return {'type': 'leaf', 'panel': node.panel_name}
    return {
        'type': 'split',
        'orientation': node.orientation.name.lower(),
        'sizes': node.sizes,
        'children': [_node_to_dict(c) for c in node.children],
    }


def _node_from_dict(data) -> SplitNode | LeafNode | None:
    if data is None:
        return None
    if data['type'] == 'leaf':
        return LeafNode(data['panel'])
    orientation = Orientation[data['orientation'].upper()]
    children = [_node_from_dict(c) for c in data.get('children', [])]
    return SplitNode(
        orientation=orientation,
        children=children,
        sizes=data.get('sizes', []),
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
