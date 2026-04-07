from wafer.core.layout.tree import (
    FloatingState,
    LayoutTree,
    LeafNode,
    Orientation,
    SplitNode,
    flatten,
    insert_panel,
    normalize_sizes,
    reinsert_from_blueprint,
    remove_panel,
)


class TestLeafNode:
    def test_panel_name(self):
        node = LeafNode("a")
        assert node.panel_name == "a"


class TestSplitNode:
    def test_panel_names_flat(self):
        node = SplitNode(
            Orientation.HORIZONTAL,
            [LeafNode("a"), LeafNode("b"), LeafNode("c")],
        )
        assert node.panel_names() == ["a", "b", "c"]

    def test_panel_names_nested(self):
        node = SplitNode(
            Orientation.HORIZONTAL,
            [
                LeafNode("a"),
                SplitNode(Orientation.VERTICAL, [LeafNode("b"), LeafNode("c")]),
            ],
        )
        assert node.panel_names() == ["a", "b", "c"]


class TestLayoutTree:
    def test_docked_names_empty(self):
        tree = LayoutTree()
        assert tree.docked_names() == []

    def test_docked_names_single_leaf(self):
        tree = LayoutTree(root=LeafNode("a"))
        assert tree.docked_names() == ["a"]

    def test_docked_names_split(self):
        tree = LayoutTree(root=SplitNode(Orientation.HORIZONTAL, [LeafNode("a"), LeafNode("b")]))
        assert set(tree.docked_names()) == {"a", "b"}

    def test_all_names(self):
        tree = LayoutTree(
            root=SplitNode(Orientation.HORIZONTAL, [LeafNode("a"), LeafNode("b")]),
            floating={"c": FloatingState(0, 0, 100, 100)},
        )
        assert tree.all_names() == {"a", "b", "c"}


class TestSerialization:
    def test_roundtrip_empty(self):
        tree = LayoutTree()
        restored = LayoutTree.from_dict(tree.to_dict())
        assert restored.root is None
        assert restored.floating == {}
        assert restored.collapsed == set()

    def test_roundtrip_complex(self):
        tree = LayoutTree(
            root=SplitNode(
                Orientation.HORIZONTAL,
                [
                    LeafNode("a"),
                    SplitNode(
                        Orientation.VERTICAL,
                        [LeafNode("b"), LeafNode("c")],
                        sizes=[200, 300],
                    ),
                ],
                sizes=[400, 500],
            ),
            floating={"d": FloatingState(10, 20, 300, 400)},
            collapsed={"b"},
        )
        restored = LayoutTree.from_dict(tree.to_dict())
        assert isinstance(restored.root, SplitNode)
        assert restored.root.orientation == Orientation.HORIZONTAL
        assert restored.root.sizes == [400, 500]
        assert len(restored.root.children) == 2
        child1 = restored.root.children[1]
        assert isinstance(child1, SplitNode)
        assert child1.sizes == [200, 300]
        assert "d" in restored.floating
        fs = restored.floating["d"]
        assert (fs.x, fs.y, fs.width, fs.height) == (10, 20, 300, 400)
        assert restored.collapsed == {"b"}


class TestRemovePanel:
    def test_remove_from_none(self):
        assert remove_panel(None, "a") is None

    def test_remove_matching_leaf(self):
        assert remove_panel(LeafNode("a"), "a") is None

    def test_remove_nonmatching_leaf(self):
        result = remove_panel(LeafNode("a"), "b")
        assert isinstance(result, LeafNode)
        assert result.panel_name == "a"

    def test_remove_from_split_collapses(self):
        node = SplitNode(Orientation.HORIZONTAL, [LeafNode("a"), LeafNode("b")])
        result = remove_panel(node, "a")
        assert isinstance(result, LeafNode)
        assert result.panel_name == "b"

    def test_remove_from_split_preserves_sizes(self):
        node = SplitNode(
            Orientation.HORIZONTAL,
            [LeafNode("a"), LeafNode("b"), LeafNode("c")],
            sizes=[100, 200, 300],
        )
        result = remove_panel(node, "b")
        assert isinstance(result, SplitNode)
        assert result.sizes == [100, 300]


class TestInsertPanel:
    def test_insert_into_none(self):
        result = insert_panel(None, "a")
        assert isinstance(result, LeafNode)
        assert result.panel_name == "a"

    def test_insert_into_leaf(self):
        result = insert_panel(LeafNode("a"), "b")
        assert isinstance(result, SplitNode)
        assert len(result.children) == 2
        names = [c.panel_name for c in result.children]
        assert names == ["a", "b"]

    def test_insert_at_position_0(self):
        result = insert_panel(LeafNode("a"), "b", position=0)
        assert isinstance(result, SplitNode)
        names = [c.panel_name for c in result.children]
        assert names == ["b", "a"]

    def test_insert_into_matching_split(self):
        node = SplitNode(
            Orientation.HORIZONTAL,
            [LeafNode("a"), LeafNode("b")],
            sizes=[100, 200],
        )
        result = insert_panel(node, "c", Orientation.HORIZONTAL)
        assert isinstance(result, SplitNode)
        assert len(result.children) == 3
        assert len(result.sizes) == 3

    def test_insert_into_different_orientation(self):
        node = SplitNode(
            Orientation.HORIZONTAL,
            [LeafNode("a"), LeafNode("b")],
        )
        result = insert_panel(node, "c", Orientation.VERTICAL)
        assert isinstance(result, SplitNode)
        assert result.orientation == Orientation.VERTICAL
        assert len(result.children) == 2


class TestFlatten:
    def test_flatten_none(self):
        assert flatten(None) is None

    def test_flatten_leaf(self):
        leaf = LeafNode("a")
        assert flatten(leaf) is leaf

    def test_flatten_no_nesting(self):
        node = SplitNode(
            Orientation.HORIZONTAL,
            [LeafNode("a"), LeafNode("b")],
            sizes=[100, 200],
        )
        result = flatten(node)
        assert isinstance(result, SplitNode)
        assert len(result.children) == 2
        assert result.sizes == [100, 200]

    def test_flatten_same_orientation(self):
        inner = SplitNode(
            Orientation.HORIZONTAL,
            [LeafNode("b"), LeafNode("c")],
            sizes=[100, 300],
        )
        outer = SplitNode(
            Orientation.HORIZONTAL,
            [LeafNode("a"), inner],
            sizes=[200, 400],
        )
        result = flatten(outer)
        assert isinstance(result, SplitNode)
        names = [c.panel_name for c in result.children]
        assert names == ["a", "b", "c"]
        assert result.sizes == [200, 100, 300]

    def test_flatten_different_orientation_preserved(self):
        inner = SplitNode(
            Orientation.VERTICAL,
            [LeafNode("b"), LeafNode("c")],
            sizes=[50, 50],
        )
        outer = SplitNode(
            Orientation.HORIZONTAL,
            [LeafNode("a"), inner],
            sizes=[100, 200],
        )
        result = flatten(outer)
        assert isinstance(result, SplitNode)
        assert len(result.children) == 2
        assert isinstance(result.children[1], SplitNode)
        assert result.children[1].orientation == Orientation.VERTICAL

    def test_flatten_deep_nesting(self):
        deep = SplitNode(
            Orientation.HORIZONTAL,
            [
                LeafNode("a"),
                SplitNode(
                    Orientation.HORIZONTAL,
                    [
                        LeafNode("b"),
                        SplitNode(
                            Orientation.HORIZONTAL,
                            [LeafNode("c"), LeafNode("d")],
                            sizes=[100, 100],
                        ),
                    ],
                    sizes=[100, 200],
                ),
            ],
            sizes=[100, 300],
        )
        result = flatten(deep)
        assert isinstance(result, SplitNode)
        names = [c.panel_name for c in result.children]
        assert names == ["a", "b", "c", "d"]

    def test_flatten_empty_sizes(self):
        node = SplitNode(
            Orientation.HORIZONTAL,
            [
                LeafNode("a"),
                SplitNode(
                    Orientation.HORIZONTAL,
                    [LeafNode("b"), LeafNode("c")],
                    sizes=[],
                ),
            ],
            sizes=[],
        )
        result = flatten(node)
        assert isinstance(result, SplitNode)
        names = [c.panel_name for c in result.children]
        assert set(names) == {"a", "b", "c"}
        assert len(result.sizes) == 3

    def test_flatten_partial_sizes(self):
        node = SplitNode(
            Orientation.HORIZONTAL,
            [LeafNode("a"), LeafNode("b"), LeafNode("c")],
            sizes=[100],
        )
        result = flatten(node)
        assert isinstance(result, SplitNode)
        assert len(result.children) == 3
        assert len(result.sizes) == 3
        assert result.sizes[0] == 100


class TestReinsertFromBlueprint:
    @staticmethod
    def _five_panel_tree():
        return SplitNode(
            Orientation.HORIZONTAL,
            [
                SplitNode(
                    Orientation.VERTICAL,
                    [LeafNode("Toolbar"), LeafNode("Folder Tree")],
                    sizes=[80, 500],
                ),
                SplitNode(
                    Orientation.VERTICAL,
                    [LeafNode("Search"), LeafNode("Grid View")],
                    sizes=[40, 540],
                ),
                LeafNode("File Viewer"),
            ],
            sizes=[200, 600, 400],
        )

    def test_reinsert_sibling_same_level(self):
        blueprint = self._five_panel_tree()
        current = remove_panel(blueprint, "Grid View")
        result = reinsert_from_blueprint(current, blueprint, "Grid View")
        names = result.panel_names()
        assert "Grid View" in names
        assert names.index("Search") < names.index("Grid View")

    def test_reinsert_root_level_leaf(self):
        blueprint = self._five_panel_tree()
        current = remove_panel(blueprint, "File Viewer")
        result = reinsert_from_blueprint(current, blueprint, "File Viewer")
        names = result.panel_names()
        assert "File Viewer" in names
        assert names.index("Grid View") < names.index("File Viewer")

    def test_reinsert_preserves_orientation(self):
        blueprint = self._five_panel_tree()
        current = remove_panel(blueprint, "Grid View")
        result = reinsert_from_blueprint(current, blueprint, "Grid View")
        for c in result.children if isinstance(result, SplitNode) else []:
            if isinstance(c, SplitNode):
                search_names = c.panel_names()
                if "Search" in search_names and "Grid View" in search_names:
                    assert c.orientation == Orientation.VERTICAL

    def test_reinsert_into_none(self):
        blueprint = SplitNode(
            Orientation.HORIZONTAL,
            [LeafNode("A"), LeafNode("B")],
            sizes=[100, 200],
        )
        result = reinsert_from_blueprint(None, blueprint, "A")
        assert isinstance(result, LeafNode)
        assert result.panel_name == "A"

    def test_reinsert_no_blueprint(self):
        current = LeafNode("A")
        result = reinsert_from_blueprint(current, None, "B")
        names = result.panel_names() if isinstance(result, SplitNode) else [result.panel_name]
        assert "B" in names

    def test_reinsert_after_multiple_removes(self):
        blueprint = self._five_panel_tree()
        current = remove_panel(blueprint, "Grid View")
        current = remove_panel(current, "File Viewer")
        current = reinsert_from_blueprint(current, blueprint, "Grid View")
        current = reinsert_from_blueprint(current, blueprint, "File Viewer")
        names = current.panel_names()
        assert names.index("Toolbar") < names.index("Folder Tree")
        assert names.index("Search") < names.index("Grid View")
        assert names.index("Grid View") < names.index("File Viewer")


class TestNormalizeSizes:
    @staticmethod
    def _default_tree():
        return SplitNode(
            Orientation.HORIZONTAL,
            [
                SplitNode(
                    Orientation.VERTICAL,
                    [LeafNode("Toolbar"), LeafNode("Folder Tree")],
                    sizes=[80, 500],
                ),
                SplitNode(
                    Orientation.VERTICAL,
                    [LeafNode("Search"), LeafNode("Grid View")],
                    sizes=[40, 540],
                ),
                LeafNode("File Viewer"),
            ],
            sizes=[200, 600, 400],
        )

    def test_no_collapsed_noop(self):
        tree = self._default_tree()
        result = normalize_sizes(tree, set())
        assert result is True
        assert tree.sizes == [200, 600, 400]

    def test_single_leaf_collapsed_keeps_zero(self):
        node = SplitNode(
            Orientation.HORIZONTAL,
            [LeafNode("A"), LeafNode("B")],
            sizes=[300, 200],
        )
        assert normalize_sizes(node, {"A", "B"}) is False

    def test_expand_restores_zero_size(self):
        node = SplitNode(
            Orientation.HORIZONTAL,
            [LeafNode("A"), LeafNode("B")],
            sizes=[0, 200],
        )
        result = normalize_sizes(node, set())
        assert result is True
        assert node.sizes[0] > 0
        assert node.sizes[1] == 200

    def test_nested_all_collapsed_then_expand_one(self):
        tree = self._default_tree()
        tree.children[1].sizes = [0, 0]
        tree.sizes = [200, 0, 400]
        collapsed = {"Grid View"}
        result = normalize_sizes(tree, collapsed)
        assert result is True
        assert tree.children[1].sizes[0] > 0
        assert tree.sizes[1] > 0

    def test_deeply_nested_ancestor_restore(self):
        deep = SplitNode(
            Orientation.HORIZONTAL,
            [
                SplitNode(
                    Orientation.VERTICAL,
                    [
                        SplitNode(
                            Orientation.HORIZONTAL,
                            [LeafNode("A"), LeafNode("B")],
                            sizes=[0, 0],
                        ),
                        LeafNode("C"),
                    ],
                    sizes=[0, 300],
                ),
                LeafNode("D"),
            ],
            sizes=[0, 500],
        )
        collapsed = {"A", "C"}
        result = normalize_sizes(deep, collapsed)
        assert result is True
        inner = deep.children[0].children[0]
        assert inner.sizes[1] > 0
        assert deep.children[0].sizes[0] > 0
        assert deep.sizes[0] > 0

    def test_none_node(self):
        assert normalize_sizes(None, set()) is False

    def test_visible_leaf(self):
        assert normalize_sizes(LeafNode("A"), set()) is True

    def test_collapsed_leaf(self):
        assert normalize_sizes(LeafNode("A"), {"A"}) is False

    def test_parent_collapsed_child_not(self):
        tree = self._default_tree()
        tree.children[1].sizes = [0, 0]
        tree.sizes = [200, 0, 400]
        collapsed = {"Search"}
        result = normalize_sizes(tree, collapsed)
        assert result is True
        assert tree.children[1].sizes[1] > 0
        assert tree.sizes[1] > 0
