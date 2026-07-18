import pytest

from PySide6 import QtCore, QtWidgets

from wafer.ui.layout.manager import LayoutManager, MODE_EDIT, MODE_LOCKED, PanelEntry
from wafer.ui.layout.tree import FloatingState, LayoutTree, LeafNode, Orientation, SplitNode, insert_panel


def _make_panel(name: str) -> QtWidgets.QWidget:
    w = QtWidgets.QWidget()
    w.setMinimumSize(50, 50)
    w.setObjectName(f"panel_{name}")
    return w


_DEFAULT_STATE = {
    "mode": MODE_LOCKED,
    "tree": {
        "root": {
            "type": "split",
            "orientation": "horizontal",
            "children": [
                {"type": "leaf", "panel": "folder"},
                {"type": "leaf", "panel": "grid"},
                {"type": "leaf", "panel": "viewer"},
            ],
            "sizes": [200, 400, 400],
        },
        "floating": {},
    },
}


@pytest.fixture
def layout_env(qtbot):
    win = QtWidgets.QMainWindow()
    win.resize(1200, 700)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)

    mgr = LayoutManager(win)
    panels = {}
    for name in ["folder", "grid", "viewer"]:
        w = _make_panel(name)
        panels[name] = w
        mgr.register(name, lambda w=w: w)

    mgr.restore_state(_DEFAULT_STATE)
    QtWidgets.QApplication.processEvents()
    return mgr, win, panels


def _register_floating(mgr, name, widget):
    mgr.register(name, lambda w=widget: w)
    mgr.toggle_panel(name)


def _register_docked(mgr, name, widget):
    mgr.register(name, lambda w=widget: w)
    mgr._tree.root = insert_panel(mgr._tree.root, name)
    mgr._rebuild()


def _process(count=5):
    for _ in range(count):
        QtWidgets.QApplication.processEvents()


def _get_splitter_sizes(mgr: LayoutManager):
    if mgr._root_splitter is None:
        return None
    return mgr._root_splitter.sizes()


class TestModeSwitch:
    def test_initial_mode_is_locked(self, layout_env):
        mgr, win, panels = layout_env
        assert mgr.mode == MODE_LOCKED

    def test_toggle_mode_switches(self, layout_env):
        mgr, win, panels = layout_env
        mgr.toggle_mode()
        assert mgr.mode == MODE_EDIT
        mgr.toggle_mode()
        assert mgr.mode == MODE_LOCKED

    def test_mode_changed_signal(self, layout_env):
        mgr, win, panels = layout_env
        received = []
        mgr.mode_changed.connect(lambda m: received.append(m))
        mgr.set_mode(MODE_EDIT)
        mgr.set_mode(MODE_LOCKED)
        assert received == [MODE_EDIT, MODE_LOCKED]


class TestPanelPreservation:
    def test_all_panels_survive_lock_edit_lock(self, layout_env):
        mgr, win, panels = layout_env
        mgr.set_mode(MODE_EDIT)
        _process()
        mgr.set_mode(MODE_LOCKED)
        _process()

        for name in panels:
            assert name in mgr.panel_names()
            assert mgr.is_panel_visible(name)

    def test_all_panels_survive_many_toggles(self, layout_env):
        mgr, win, panels = layout_env
        for _ in range(5):
            mgr.toggle_mode()
            _process()

        for name in panels:
            assert name in mgr.panel_names()

    def test_docked_names_stable_after_roundtrip(self, layout_env):
        mgr, win, panels = layout_env
        initial_docked = set(mgr._tree.docked_names())

        mgr.set_mode(MODE_EDIT)
        _process()
        mgr.set_mode(MODE_LOCKED)
        _process()

        assert set(mgr._tree.docked_names()) == initial_docked


class TestFloatingTracking:
    def test_register_floating_creates_window_in_locked(self, layout_env):
        mgr, win, panels = layout_env
        w = _make_panel("dyn")
        _register_floating(mgr, "dyn", w)
        _process()

        entry = mgr._panels["dyn"]
        assert entry.floating_window is not None
        assert "dyn" in mgr._tree.floating

    def test_floating_survives_lock_to_edit(self, layout_env):
        mgr, win, panels = layout_env
        w = _make_panel("dyn")
        _register_floating(mgr, "dyn", w)
        _process()

        mgr.set_mode(MODE_EDIT)
        _process()

        entry = mgr._panels["dyn"]
        assert mgr.is_panel_visible("dyn")
        assert entry.dock_widget is not None
        assert entry.dock_widget.isFloating()

    def test_floating_survives_lock_edit_lock(self, layout_env):
        mgr, win, panels = layout_env
        w = _make_panel("dyn")
        _register_floating(mgr, "dyn", w)
        _process()

        mgr.set_mode(MODE_EDIT)
        _process()
        mgr.set_mode(MODE_LOCKED)
        _process()

        entry = mgr._panels["dyn"]
        assert mgr.is_panel_visible("dyn")
        assert entry.floating_window is not None
        assert "dyn" in mgr._tree.floating

    def test_floating_survives_many_toggles(self, layout_env):
        mgr, win, panels = layout_env
        w = _make_panel("dyn")
        _register_floating(mgr, "dyn", w)
        _process()

        for _ in range(6):
            mgr.toggle_mode()
            _process()

        assert mgr.is_panel_visible("dyn")
        assert "dyn" in mgr._tree.floating

    def test_dock_float_changed_tracks_floating(self, layout_env):
        mgr, win, panels = layout_env
        mgr.set_mode(MODE_EDIT)
        _process()

        entry = mgr._panels["viewer"]
        assert entry.dock_widget is not None
        entry.dock_widget.setFloating(True)
        _process()

        assert "viewer" in mgr._tree.floating

    def test_close_floating_windows_closes_and_clears(self, layout_env):
        mgr, win, panels = layout_env
        w = _make_panel("dyn")
        _register_floating(mgr, "dyn", w)
        _process()

        window = mgr._panels["dyn"].floating_window
        assert window is not None

        mgr.close_floating_windows()
        _process()

        assert mgr._panels["dyn"].floating_window is None
        assert not window.isVisible()
        assert "dyn" in mgr.panel_names()

    def test_close_floating_windows_survives_severed_transient_parent(self, layout_env):
        mgr, win, panels = layout_env
        w = _make_panel("dyn")
        _register_floating(mgr, "dyn", w)
        _process()

        window = mgr._panels["dyn"].floating_window
        handle = window.windowHandle()
        if handle is not None:
            handle.setTransientParent(None)

        mgr.close_floating_windows()
        _process()

        assert mgr._panels["dyn"].floating_window is None
        assert not window.isVisible()



class TestDynamicPanels:
    def test_dynamic_panel_registers_floating(self, layout_env):
        mgr, win, panels = layout_env
        w = _make_panel("dynamic_1")
        _register_floating(mgr, "dynamic_1", w)
        _process()

        assert "dynamic_1" in mgr.panel_names()
        assert "dynamic_1" in mgr._tree.floating

    def test_dynamic_panel_survives_mode_switch(self, layout_env):
        mgr, win, panels = layout_env
        w = _make_panel("dynamic_1")
        _register_floating(mgr, "dynamic_1", w)
        _process()

        mgr.set_mode(MODE_EDIT)
        _process()
        mgr.set_mode(MODE_LOCKED)
        _process()

        assert mgr.is_panel_visible("dynamic_1")
        assert "dynamic_1" in mgr._tree.floating

    def test_dynamic_panel_in_edit_mode(self, layout_env):
        mgr, win, panels = layout_env
        mgr.set_mode(MODE_EDIT)
        _process()

        w = _make_panel("dynamic_1")
        _register_floating(mgr, "dynamic_1", w)
        _process()

        assert mgr.is_panel_visible("dynamic_1")
        entry = mgr._panels["dynamic_1"]
        assert entry.dock_widget is not None
        assert mgr.mode == MODE_EDIT

    def test_unregister_removes_panel(self, layout_env):
        mgr, win, panels = layout_env
        w = _make_panel("dynamic_1")
        _register_floating(mgr, "dynamic_1", w)
        _process()

        mgr.unregister("dynamic_1")
        _process()

        assert "dynamic_1" not in mgr.panel_names()
        assert "dynamic_1" not in mgr._tree.floating


class TestToggleCollapse:
    def test_toggle_collapses_docked_panel(self, layout_env):
        mgr, win, panels = layout_env
        _process(10)

        assert mgr.is_panel_visible("viewer")
        mgr.toggle_panel("viewer")
        _process()

        assert not mgr.is_panel_visible("viewer")
        assert mgr.is_panel_collapsed("viewer")
        assert "viewer" in mgr._tree.collapsed
        assert "viewer" in set(mgr._tree.docked_names())

    def test_toggle_expands_collapsed_panel(self, layout_env):
        mgr, win, panels = layout_env
        _process(10)

        mgr.toggle_panel("viewer")
        _process()
        mgr.toggle_panel("viewer")
        _process()

        assert mgr.is_panel_visible("viewer")
        assert not mgr.is_panel_collapsed("viewer")
        assert "viewer" not in mgr._tree.collapsed

    def test_collapsed_panel_has_zero_size(self, layout_env):
        mgr, win, panels = layout_env
        _process(10)

        mgr.toggle_panel("viewer")
        _process(10)

        widget = panels["viewer"]
        parent = widget.parent()
        if isinstance(parent, QtWidgets.QSplitter):
            idx = parent.indexOf(widget)
            sizes = parent.sizes()
            assert sizes[idx] == 0

    def test_collapsed_survives_mode_roundtrip(self, layout_env):
        mgr, win, panels = layout_env
        _process(10)

        mgr.toggle_panel("viewer")
        _process()
        assert mgr.is_panel_collapsed("viewer")

        mgr.set_mode(MODE_EDIT)
        _process()
        mgr.set_mode(MODE_LOCKED)
        _process()

        assert mgr.is_panel_collapsed("viewer")

    def test_multiple_panels_collapsed(self, layout_env):
        mgr, win, panels = layout_env
        _process(10)

        mgr.toggle_panel("folder")
        mgr.toggle_panel("viewer")
        _process()

        assert mgr.is_panel_collapsed("folder")
        assert mgr.is_panel_collapsed("viewer")
        assert mgr.is_panel_visible("grid")


class TestPanelSolo:
    def test_solo_collapses_other_docked_panels(self, layout_env):
        mgr, win, panels = layout_env
        _process(10)

        assert mgr.solo_panel("grid")
        _process()

        assert mgr.is_panel_visible("grid")
        assert mgr.is_panel_collapsed("folder")
        assert mgr.is_panel_collapsed("viewer")

    def test_solo_again_expands_all_docked_panels(self, layout_env):
        mgr, win, panels = layout_env
        _process(10)
        mgr.toggle_panel("folder")
        _process()

        assert mgr.solo_panel("grid")
        _process()
        assert mgr.solo_panel("grid")
        _process()

        assert mgr._tree.collapsed == set()

    def test_solo_shows_target_that_was_collapsed_then_expands_all(self, layout_env):
        mgr, win, panels = layout_env
        _process(10)
        mgr.toggle_panel("grid")
        _process()

        assert mgr.solo_panel("grid")
        _process()

        assert mgr.is_panel_visible("grid")
        assert mgr.is_panel_collapsed("folder")
        assert mgr.is_panel_collapsed("viewer")

        assert mgr.solo_panel("grid")
        _process()
        assert mgr._tree.collapsed == set()

    def test_solo_switches_target(self, layout_env):
        mgr, win, panels = layout_env
        _process(10)
        mgr.toggle_panel("folder")
        _process()

        assert mgr.solo_panel("grid")
        _process()
        assert mgr.solo_panel("viewer")
        _process()

        assert mgr.is_panel_visible("viewer")
        assert mgr.is_panel_collapsed("folder")
        assert mgr.is_panel_collapsed("grid")

        assert mgr.solo_panel("viewer")
        _process()
        assert mgr._tree.collapsed == set()

    def test_solo_survives_save_restore_and_re_solo_expands(self, layout_env):
        mgr, win, panels = layout_env
        _process(10)

        assert mgr.solo_panel("grid")
        _process()
        soloed = set(mgr._tree.collapsed)

        mgr.restore_state(mgr.save_state())
        _process(10)

        assert mgr._tree.collapsed == soloed
        assert mgr.is_panel_visible("grid")

        assert mgr.solo_panel("grid")
        _process()
        assert mgr._tree.collapsed == set()

    def test_solo_collapses_nested_sibling_branch(self, qtbot):
        win = QtWidgets.QMainWindow()
        win.resize(1200, 700)
        qtbot.addWidget(win)
        win.show()
        qtbot.waitExposed(win)

        mgr = LayoutManager(win)
        for name in ["a", "b", "c", "d"]:
            w = _make_panel(name)
            mgr.register(name, lambda w=w: w)

        mgr.restore_state(
            {
                "mode": MODE_LOCKED,
                "tree": {
                    "root": {
                        "type": "split",
                        "orientation": "horizontal",
                        "children": [
                            {
                                "type": "split",
                                "orientation": "vertical",
                                "children": [
                                    {"type": "leaf", "panel": "a"},
                                    {"type": "leaf", "panel": "b"},
                                ],
                                "sizes": [300, 300],
                            },
                            {
                                "type": "split",
                                "orientation": "vertical",
                                "children": [
                                    {"type": "leaf", "panel": "c"},
                                    {"type": "leaf", "panel": "d"},
                                ],
                                "sizes": [300, 300],
                            },
                        ],
                        "sizes": [500, 500],
                    },
                    "floating": {},
                },
            }
        )
        _process(10)

        assert mgr.solo_panel("c")
        _process(10)

        root_sizes = mgr._root_splitter.sizes()
        right_sizes = mgr._root_splitter.widget(1).sizes()
        assert root_sizes[0] == 0
        assert root_sizes[1] > 0
        assert right_sizes[0] > 0
        assert right_sizes[1] == 0

    def test_solo_dormant_panel_is_noop(self, layout_env):
        mgr, win, panels = layout_env
        w = _make_panel("dyn")
        mgr.register("dyn", lambda: w)
        before = set(mgr._tree.collapsed)

        assert not mgr.solo_panel("dyn")
        _process()

        assert mgr._tree.collapsed == before
        assert "dyn" in mgr.dormant_panels()

    def test_solo_floating_panel_maximizes_without_collapsing_docked_panels(self, layout_env):
        mgr, win, panels = layout_env
        w = _make_panel("dyn")
        _register_floating(mgr, "dyn", w)
        _process()
        before = set(mgr._tree.collapsed)

        assert mgr.solo_panel("dyn")
        _process()

        entry = mgr._panels["dyn"]
        assert entry.floating_window is not None
        assert entry.floating_window.windowState() & QtCore.Qt.WindowMaximized
        assert mgr._tree.collapsed == before

    def test_panel_at_widget_resolves_locked_panel_descendant(self, layout_env):
        mgr, win, panels = layout_env
        child = QtWidgets.QWidget(panels["viewer"])

        assert mgr.panel_at_widget(child) == "viewer"
        assert mgr.panel_at_widget(win) is None

    def test_panel_at_widget_resolves_floating_panel_descendant(self, layout_env):
        mgr, win, panels = layout_env
        w = _make_panel("dyn")
        _register_floating(mgr, "dyn", w)
        child = QtWidgets.QWidget(w)

        assert mgr.panel_at_widget(child) == "dyn"

    def test_manual_toggle_after_solo_expands_panel(self, layout_env):
        mgr, win, panels = layout_env
        _process(10)
        assert mgr.solo_panel("grid")
        _process()
        assert mgr.is_panel_collapsed("folder")

        mgr.toggle_panel("folder")
        _process()

        assert mgr.is_panel_visible("folder")


class TestToggleEditMode:
    def test_toggle_in_edit_switches_to_locked(self, layout_env):
        mgr, win, panels = layout_env
        mgr.set_mode(MODE_EDIT)
        _process()

        mgr.toggle_panel("viewer")
        _process()

        assert mgr.mode == MODE_LOCKED
        assert mgr.is_panel_collapsed("viewer")

    def test_toggle_collapsed_in_edit_switches_to_locked_and_expands(self, layout_env):
        mgr, win, panels = layout_env
        mgr.toggle_panel("viewer")
        _process()
        assert mgr.is_panel_collapsed("viewer")

        mgr.set_mode(MODE_EDIT)
        _process()

        mgr.toggle_panel("viewer")
        _process()

        assert mgr.mode == MODE_LOCKED
        assert mgr.is_panel_visible("viewer")


class TestToggleFloating:
    def test_toggle_floating_makes_dormant(self, layout_env):
        mgr, win, panels = layout_env
        w = _make_panel("dyn")
        _register_floating(mgr, "dyn", w)
        _process()

        mgr.toggle_panel("dyn")
        _process()

        assert not mgr.is_panel_visible("dyn")
        assert "dyn" in mgr.dormant_panels()
        entry = mgr._panels["dyn"]
        assert entry.floating_window is None

    def test_toggle_floating_preserves_position(self, layout_env):
        mgr, win, panels = layout_env
        w = _make_panel("dyn")
        _register_floating(mgr, "dyn", w)
        _process()

        entry = mgr._panels["dyn"]
        assert entry.floating_window is not None

        mgr.toggle_panel("dyn")
        _process()

        assert entry.last_floating is not None

    def test_toggle_floating_shows_and_hides(self, layout_env):
        mgr, win, panels = layout_env
        w = _make_panel("dyn")
        _register_floating(mgr, "dyn", w)
        _process()

        for _ in range(3):
            mgr.toggle_panel("dyn")
            _process()
            assert not mgr.is_panel_visible("dyn")
            mgr.toggle_panel("dyn")
            _process()
            assert mgr.is_panel_visible("dyn")


class TestToggleDormant:
    def test_toggle_restores_dormant_as_floating(self, layout_env):
        mgr, win, panels = layout_env
        w = _make_panel("dyn")
        _register_floating(mgr, "dyn", w)
        _process()

        mgr.toggle_panel("dyn")
        _process()
        assert "dyn" in mgr.dormant_panels()

        mgr.toggle_panel("dyn")
        _process()

        assert mgr.is_panel_visible("dyn")
        entry = mgr._panels["dyn"]
        assert entry.floating_window is not None

    def test_toggle_dormant_uses_last_floating_position(self, layout_env):
        mgr, win, panels = layout_env
        w = _make_panel("dyn")
        _register_floating(mgr, "dyn", w)
        _process()

        mgr.toggle_panel("dyn")
        _process()

        entry = mgr._panels["dyn"]
        saved_fs = entry.last_floating
        assert saved_fs is not None

        mgr.toggle_panel("dyn")
        _process()

        assert "dyn" in mgr._tree.floating
        fs = mgr._tree.floating["dyn"]
        assert fs.x == saved_fs.x
        assert fs.y == saved_fs.y

    def test_toggle_unknown_panel_is_noop(self, layout_env):
        mgr, win, panels = layout_env
        mgr.toggle_panel("nonexistent")

    def test_cascade_positioning_offsets_windows(self, layout_env):
        mgr, win, panels = layout_env
        _process()

        mgr.register("dyn_a", lambda: _make_panel("dyn_a"))
        mgr.register("dyn_b", lambda: _make_panel("dyn_b"))

        mgr.toggle_panel("dyn_a")
        _process()
        mgr.toggle_panel("dyn_b")
        _process()

        fs_a = mgr._tree.floating["dyn_a"]
        fs_b = mgr._tree.floating["dyn_b"]
        assert fs_a.x != fs_b.x or fs_a.y != fs_b.y


class TestDormantPanels:
    def test_dormant_panels_initially_empty(self, layout_env):
        mgr, win, panels = layout_env
        assert mgr.dormant_panels() == []

    def test_dock_close_makes_dormant(self, layout_env):
        mgr, win, panels = layout_env
        mgr.set_mode(MODE_EDIT)
        _process()

        entry = mgr._panels["viewer"]
        assert entry.dock_widget is not None
        entry.dock_widget.close()
        _process()

        assert "viewer" in mgr.dormant_panels()
        assert "viewer" not in set(mgr._tree.docked_names())
        assert "viewer" not in mgr._tree.floating

    def test_dock_close_preserves_last_floating(self, layout_env):
        mgr, win, panels = layout_env
        mgr.set_mode(MODE_EDIT)
        _process()

        entry = mgr._panels["viewer"]
        entry.dock_widget.close()
        _process()

        assert entry.last_floating is not None

    def test_floating_close_makes_dormant(self, layout_env):
        mgr, win, panels = layout_env
        w = _make_panel("dyn")
        _register_floating(mgr, "dyn", w)
        _process()

        entry = mgr._panels["dyn"]
        entry.floating_window.close()
        _process()

        assert "dyn" in mgr.dormant_panels()
        assert entry.last_floating is not None

    def test_dormant_panel_stays_registered(self, layout_env):
        mgr, win, panels = layout_env
        mgr.set_mode(MODE_EDIT)
        _process()

        mgr._panels["viewer"].dock_widget.close()
        _process()

        assert "viewer" in mgr.panel_names()
        assert "viewer" in mgr.dormant_panels()

    def test_toggle_restores_closed_panel(self, layout_env):
        mgr, win, panels = layout_env
        mgr.set_mode(MODE_EDIT)
        _process()

        mgr._panels["viewer"].dock_widget.close()
        _process()
        assert "viewer" in mgr.dormant_panels()

        mgr.toggle_panel("viewer")
        _process()

        assert mgr.is_panel_visible("viewer")
        assert "viewer" not in mgr.dormant_panels()


class TestSizeStability:
    def test_splitter_sizes_preserved_after_roundtrip(self, layout_env):
        mgr, win, panels = layout_env
        _process(10)

        initial_sizes = _get_splitter_sizes(mgr)
        assert initial_sizes is not None
        assert len(initial_sizes) > 0

        mgr.set_mode(MODE_EDIT)
        _process(10)
        mgr.set_mode(MODE_LOCKED)
        _process(10)

        after_sizes = _get_splitter_sizes(mgr)
        assert after_sizes is not None
        assert len(after_sizes) == len(initial_sizes)
        for a, b in zip(initial_sizes, after_sizes):
            assert abs(a - b) <= max(a * 0.15, 20), f"Size drift: {a} -> {b}"

    def test_sizes_stable_across_many_switches(self, layout_env):
        mgr, win, panels = layout_env
        _process(10)

        initial_sizes = _get_splitter_sizes(mgr)
        assert initial_sizes is not None

        for _ in range(4):
            mgr.set_mode(MODE_EDIT)
            _process(10)
            mgr.set_mode(MODE_LOCKED)
            _process(10)

        final_sizes = _get_splitter_sizes(mgr)
        assert final_sizes is not None
        for a, b in zip(initial_sizes, final_sizes):
            assert abs(a - b) <= max(a * 0.15, 20), f"Size drift over cycles: {a} -> {b}"


class TestSaveRestore:
    def test_save_restore_locked_mode(self, layout_env):
        mgr, win, panels = layout_env
        _process()

        state = mgr.save_state()
        assert "mode" in state
        assert "tree" in state
        assert state["mode"] == MODE_LOCKED

    def test_restore_preserves_panels(self, layout_env):
        mgr, win, panels = layout_env
        _process()

        state = mgr.save_state()

        mgr.toggle_panel("viewer")
        _process()

        mgr.restore_state(state)
        _process()

        assert mgr.mode == MODE_LOCKED
        assert "viewer" in set(mgr._tree.docked_names())

    def test_restore_in_edit_mode(self, layout_env):
        mgr, win, panels = layout_env
        mgr.set_mode(MODE_EDIT)
        _process()

        state = mgr.save_state()
        assert state["mode"] == MODE_EDIT

        mgr.set_mode(MODE_LOCKED)
        _process()

        mgr.restore_state(state)
        _process()

        assert mgr.mode == MODE_EDIT
        for name in panels:
            assert mgr.is_panel_visible(name)

    def test_save_restore_collapsed(self, layout_env):
        mgr, win, panels = layout_env
        _process(10)

        mgr.toggle_panel("viewer")
        _process()
        assert mgr.is_panel_collapsed("viewer")

        state = mgr.save_state()
        mgr.toggle_panel("viewer")
        _process()
        assert not mgr.is_panel_collapsed("viewer")

        mgr.restore_state(state)
        _process()

        assert mgr.is_panel_collapsed("viewer")

    def test_save_restore_dormant_stays_dormant(self, layout_env):
        mgr, win, panels = layout_env
        mgr.set_mode(MODE_EDIT)
        _process()
        mgr._panels["viewer"].dock_widget.close()
        _process()

        state = mgr.save_state()
        assert "viewer" in state.get("dormant", {})

        mgr.restore_state(state)
        _process()

        assert "viewer" in mgr.dormant_panels()
        assert "viewer" not in mgr._tree.floating

    def test_save_add_close_restore_new_panel_stays_dormant(self, layout_env):
        mgr, win, panels = layout_env
        state = mgr.save_state()

        w = _make_panel("new_panel")
        _register_floating(mgr, "new_panel", w)
        _process()
        mgr._panels["new_panel"].floating_window.close()
        _process()
        assert "new_panel" in mgr.dormant_panels()

        mgr.restore_state(state)
        _process()

        assert "new_panel" in mgr.dormant_panels()
        assert "new_panel" not in mgr._tree.floating
        entry = mgr._panels["new_panel"]
        assert entry.dock_widget is None
        assert entry.floating_window is None

    def test_save_restore_roundtrip_tree(self, layout_env):
        mgr, win, panels = layout_env
        mgr.toggle_panel("folder")
        _process()

        state = mgr.save_state()
        tree_dict = state["tree"]

        restored_tree = LayoutTree.from_dict(tree_dict)
        assert "folder" in restored_tree.collapsed


class TestDockOptions:
    def test_tabs_not_allowed(self, layout_env):
        mgr, win, panels = layout_env
        opts = win.dockOptions()
        assert not (opts & QtWidgets.QMainWindow.AllowTabbedDocks)

    def test_nesting_allowed(self, layout_env):
        mgr, win, panels = layout_env
        opts = win.dockOptions()
        assert opts & QtWidgets.QMainWindow.AllowNestedDocks


class TestEditModeDockBehavior:
    def test_edit_mode_creates_dock_widgets(self, layout_env):
        mgr, win, panels = layout_env
        mgr.set_mode(MODE_EDIT)
        _process()

        for name in panels:
            entry = mgr._panels[name]
            assert entry.dock_widget is not None

    def test_locked_mode_clears_dock_widgets(self, layout_env):
        mgr, win, panels = layout_env
        mgr.set_mode(MODE_EDIT)
        _process()
        mgr.set_mode(MODE_LOCKED)
        _process()

        for name in panels:
            entry = mgr._panels[name]
            assert entry.dock_widget is None

    def test_edit_mode_dd_float_creates_floating_dock(self, layout_env):
        mgr, win, panels = layout_env
        mgr.set_mode(MODE_EDIT)
        _process()

        entry = mgr._panels["viewer"]
        entry.dock_widget.setFloating(True)
        _process()

        assert entry.dock_widget is not None
        assert entry.dock_widget.isFloating()
        assert entry.floating_window is None
        assert "viewer" in mgr._tree.floating


class TestDockPositionSync:
    def test_tree_reinferred_on_every_edit_sync(self, layout_env):
        mgr, win, panels = layout_env
        mgr.set_mode(MODE_EDIT)
        _process(10)

        names_before = mgr._tree.docked_names()
        assert set(names_before) == {"folder", "grid", "viewer"}

        mgr._sync_tree_from_current()
        names_after = mgr._tree.docked_names()
        assert set(names_after) == {"folder", "grid", "viewer"}
        assert mgr._tree.root is not None

    def test_rearranged_docks_reflected_in_tree(self, layout_env):
        mgr, win, panels = layout_env
        mgr.set_mode(MODE_EDIT)
        _process(10)

        folder_dock = mgr._panels["folder"].dock_widget
        viewer_dock = mgr._panels["viewer"].dock_widget
        assert folder_dock is not None
        assert viewer_dock is not None

        win.splitDockWidget(viewer_dock, folder_dock, QtCore.Qt.Horizontal)
        _process(10)

        mgr._sync_tree_from_current()
        names = mgr._tree.docked_names()
        assert set(names) == {"folder", "grid", "viewer"}
        assert mgr._tree.root is not None

    def test_rearranged_docks_reflected_in_splitter(self, layout_env):
        mgr, win, panels = layout_env
        mgr.set_mode(MODE_EDIT)
        _process(10)

        folder_dock = mgr._panels["folder"].dock_widget
        viewer_dock = mgr._panels["viewer"].dock_widget
        win.splitDockWidget(viewer_dock, folder_dock, QtCore.Qt.Horizontal)
        _process(10)

        mgr.set_mode(MODE_LOCKED)
        _process(10)

        assert mgr._root_splitter is not None
        docked = mgr._tree.docked_names()
        assert set(docked) == {"folder", "grid", "viewer"}

    def test_tree_structure_updated_after_split(self, layout_env):
        mgr, win, panels = layout_env
        mgr.set_mode(MODE_EDIT)
        _process(10)

        grid_dock = mgr._panels["grid"].dock_widget
        viewer_dock = mgr._panels["viewer"].dock_widget
        win.splitDockWidget(grid_dock, viewer_dock, QtCore.Qt.Vertical)
        _process(10)

        mgr._sync_tree_from_current()
        root = mgr._tree.root
        assert root is not None
        assert isinstance(root, SplitNode)


class TestFloatingWindowZOrder:
    def test_floating_window_has_parent(self, layout_env):
        mgr, win, panels = layout_env
        w = _make_panel("dyn")
        _register_floating(mgr, "dyn", w)
        _process()

        entry = mgr._panels["dyn"]
        assert entry.floating_window is not None
        assert entry.floating_window.parent() is win

    def test_floating_window_stays_on_top_after_mode_switch(self, layout_env):
        mgr, win, panels = layout_env
        w = _make_panel("dyn")
        _register_floating(mgr, "dyn", w)
        _process()

        mgr.set_mode(MODE_EDIT)
        _process()
        mgr.set_mode(MODE_LOCKED)
        _process()

        entry = mgr._panels["dyn"]
        assert entry.floating_window is not None
        assert entry.floating_window.parent() is win

    def test_register_as_floating_has_parent(self, layout_env):
        mgr, win, panels = layout_env
        w = _make_panel("dynamic_1")
        _register_floating(mgr, "dynamic_1", w)
        _process()

        entry = mgr._panels["dynamic_1"]
        assert entry.floating_window is not None
        assert entry.floating_window.parent() is win


class TestWidgetRecovery:
    def test_unregister_floating_widget_survives(self, layout_env):
        import shiboken6

        mgr, win, panels = layout_env
        w = _make_panel("dyn")
        _register_floating(mgr, "dyn", w)
        _process()

        mgr.unregister("dyn")
        _process(10)

        assert shiboken6.isValid(w)

    def test_unregister_docked_widget_survives(self, layout_env):
        import shiboken6

        mgr, win, panels = layout_env
        w = _make_panel("dyn")
        _register_docked(mgr, "dyn", w)
        _process()

        mgr.unregister("dyn")
        _process(10)

        assert shiboken6.isValid(w)


class TestDoubleRegister:
    def test_double_register_replaces_old(self, layout_env):
        mgr, win, panels = layout_env
        w1 = _make_panel("dyn")
        _register_floating(mgr, "dyn", w1)
        _process()

        w2 = _make_panel("dyn")
        mgr.register("dyn", lambda: w2)
        _process()

        entry = mgr._panels["dyn"]
        assert entry.factory() is w2

    def test_double_register_no_old_floating_leak(self, layout_env):
        mgr, win, panels = layout_env
        w1 = _make_panel("dyn")
        _register_floating(mgr, "dyn", w1)
        _process()

        old_window = mgr._panels["dyn"].floating_window

        w2 = _make_panel("dyn")
        mgr.register("dyn", lambda: w2)
        _process()

        new_entry = mgr._panels["dyn"]
        assert new_entry.floating_window is None
        assert old_window is not None


class TestRestoreGhostEntries:
    def test_restore_filters_unregistered_docked(self, layout_env):
        mgr, win, panels = layout_env

        state_dict = {
            "mode": MODE_LOCKED,
            "tree": {
                "root": {
                    "type": "split",
                    "orientation": "horizontal",
                    "children": [
                        {"type": "leaf", "panel": "folder"},
                        {"type": "leaf", "panel": "grid"},
                        {"type": "leaf", "panel": "viewer"},
                        {"type": "leaf", "panel": "ghost_panel"},
                    ],
                    "sizes": [100, 200, 300, 400],
                },
                "floating": {},
            },
        }

        mgr.restore_state(state_dict)
        _process()

        assert "ghost_panel" not in set(mgr._tree.docked_names())

    def test_restore_filters_unregistered_floating(self, layout_env):
        mgr, win, panels = layout_env

        state_dict = {
            "mode": MODE_LOCKED,
            "tree": {
                "root": {
                    "type": "split",
                    "orientation": "horizontal",
                    "children": [
                        {"type": "leaf", "panel": "folder"},
                        {"type": "leaf", "panel": "grid"},
                        {"type": "leaf", "panel": "viewer"},
                    ],
                    "sizes": [100, 200, 300],
                },
                "floating": {
                    "ghost_float": {"x": 0, "y": 0, "width": 100, "height": 100},
                },
            },
        }

        mgr.restore_state(state_dict)
        _process()

        assert "ghost_float" not in mgr._tree.floating

    def test_restore_filters_unregistered_collapsed(self, layout_env):
        mgr, win, panels = layout_env

        state_dict = {
            "mode": MODE_LOCKED,
            "tree": {
                "root": {
                    "type": "split",
                    "orientation": "horizontal",
                    "children": [
                        {"type": "leaf", "panel": "folder"},
                        {"type": "leaf", "panel": "grid"},
                        {"type": "leaf", "panel": "viewer"},
                    ],
                    "sizes": [100, 200, 300],
                },
                "floating": {},
                "collapsed": ["ghost_panel", "viewer"],
            },
        }

        mgr.restore_state(state_dict)
        _process()

        assert "ghost_panel" not in mgr._tree.collapsed
        assert "viewer" in mgr._tree.collapsed


class TestEditModeRebuild:
    def test_register_docked_in_edit_mode(self, layout_env):
        mgr, win, panels = layout_env
        mgr.set_mode(MODE_EDIT)
        _process()

        w = _make_panel("dyn")
        _register_docked(mgr, "dyn", w)
        _process()

        entry = mgr._panels["dyn"]
        assert entry.dock_widget is not None
        assert "dyn" in set(mgr._tree.docked_names())


class TestRestoreDormantPanels:
    def test_extra_docked_panel_becomes_dormant_on_restore(self, layout_env):
        mgr, win, panels = layout_env
        state = mgr.save_state()
        _process()

        w = _make_panel("extra")
        _register_docked(mgr, "extra", w)
        _process()

        mgr.restore_state(state)
        _process()

        assert "extra" in mgr.dormant_panels()
        assert "extra" not in mgr._tree.floating

    def test_extra_visible_floating_panel_stays_floating_on_restore(self, layout_env):
        mgr, win, panels = layout_env
        state = mgr.save_state()
        _process()

        w = _make_panel("extra")
        _register_floating(mgr, "extra", w)
        _process()

        mgr.restore_state(state)
        _process()

        assert "extra" in mgr._tree.floating
        assert "extra" not in mgr.dormant_panels()

    def test_extra_collapsed_panel_becomes_dormant_on_restore(self, layout_env):
        mgr, win, panels = layout_env

        w = _make_panel("extra")
        _register_docked(mgr, "extra", w)
        _process()
        mgr.toggle_panel("extra")
        _process()
        assert mgr.is_panel_collapsed("extra")

        state_without_extra = {
            "mode": MODE_LOCKED,
            "tree": {
                "root": {
                    "type": "split",
                    "orientation": "horizontal",
                    "children": [
                        {"type": "leaf", "panel": "folder"},
                        {"type": "leaf", "panel": "grid"},
                        {"type": "leaf", "panel": "viewer"},
                    ],
                    "sizes": [100, 200, 300],
                },
                "floating": {},
                "collapsed": [],
            },
        }

        mgr.restore_state(state_without_extra)
        _process()

        assert "extra" in mgr.dormant_panels()
        assert "extra" not in mgr._tree.floating
        assert not mgr.is_panel_collapsed("extra")

    def test_extra_dormant_panel_stays_dormant_on_restore(self, layout_env):
        mgr, win, panels = layout_env
        _process()

        w = _make_panel("extra")
        _register_floating(mgr, "extra", w)
        _process()

        mgr.toggle_panel("extra")
        _process()
        assert "extra" in mgr.dormant_panels()

        state_without_extra = {
            "mode": MODE_LOCKED,
            "tree": {
                "root": {
                    "type": "split",
                    "orientation": "horizontal",
                    "children": [
                        {"type": "leaf", "panel": "folder"},
                        {"type": "leaf", "panel": "grid"},
                        {"type": "leaf", "panel": "viewer"},
                    ],
                    "sizes": [100, 200, 300],
                },
                "floating": {},
                "collapsed": [],
            },
        }

        mgr.restore_state(state_without_extra)
        _process()

        assert "extra" in mgr.dormant_panels()
        assert "extra" not in mgr._tree.floating

    def test_extra_visible_docked_panel_becomes_floating_in_edit_mode_restore(self, layout_env):
        mgr, win, panels = layout_env
        mgr.set_mode(MODE_EDIT)
        _process()
        state = mgr.save_state()

        w = _make_panel("extra")
        _register_docked(mgr, "extra", w)
        _process()

        mgr.restore_state(state)
        _process()

        assert "extra" in mgr._tree.floating
        assert "extra" not in mgr.dormant_panels()

    def test_extra_unshown_panel_stays_dormant_on_restore(self, layout_env):
        mgr, win, panels = layout_env
        state = mgr.save_state()
        _process()

        mgr.register("extra", lambda: _make_panel("extra"))

        mgr.restore_state(state)
        _process()

        assert "extra" in mgr.dormant_panels()
        assert "extra" not in mgr._tree.floating

    def test_mode_changed_emitted_on_restore(self, layout_env, qtbot):
        mgr, win, panels = layout_env
        assert mgr.mode == MODE_LOCKED

        state = {
            "mode": MODE_EDIT,
            "tree": mgr.save_state()["tree"],
        }

        with qtbot.waitSignal(mgr.mode_changed, timeout=1000) as blocker:
            mgr.restore_state(state)
            _process()

        assert blocker.args == [MODE_EDIT]
        assert mgr.mode == MODE_EDIT

    def test_mode_changed_not_emitted_same_mode(self, layout_env, qtbot):
        mgr, win, panels = layout_env
        assert mgr.mode == MODE_LOCKED

        state = mgr.save_state()
        _process()

        signal_fired = []
        mgr.mode_changed.connect(lambda m: signal_fired.append(m))

        mgr.restore_state(state)
        _process()

        assert signal_fired == []


class TestUnregisterCollapsed:
    def test_unregister_collapsed_cleans_up(self, layout_env):
        mgr, win, panels = layout_env
        mgr.toggle_panel("viewer")
        _process()

        assert mgr.is_panel_collapsed("viewer")

        mgr.unregister("viewer")
        _process()

        assert "viewer" not in mgr._tree.collapsed
        assert "viewer" not in mgr.panel_names()


class TestClosableOption:
    def test_register_non_closable(self, layout_env):
        mgr, win, panels = layout_env
        w = _make_panel("toolbar")
        mgr.register("toolbar", lambda: w, closable=False)
        entry = mgr._panels["toolbar"]
        assert entry.closable is False

    def test_register_default_closable(self, layout_env):
        mgr, win, panels = layout_env
        entry = mgr._panels["folder"]
        assert entry.closable is True

    def test_non_closable_toggle_from_visible_collapses(self, layout_env):
        mgr, win, panels = layout_env
        w = _make_panel("toolbar")
        mgr.register("toolbar", lambda: w, closable=False)
        mgr._tree.root = insert_panel(mgr._tree.root, "toolbar")
        mgr._rebuild()
        _process()

        assert mgr.is_panel_visible("toolbar")
        mgr.toggle_panel("toolbar")
        _process()
        assert mgr.is_panel_collapsed("toolbar")

        mgr.toggle_panel("toolbar")
        _process()
        assert mgr.is_panel_visible("toolbar")

    def test_non_closable_toggle_from_dormant_shows_panel(self, layout_env):
        mgr, win, panels = layout_env
        w = _make_panel("toolbar")
        mgr.register("toolbar", lambda: w, closable=False)
        _process()

        assert "toolbar" in mgr.dormant_panels()
        mgr.toggle_panel("toolbar")
        _process()
        assert "toolbar" in mgr._tree.floating

    def test_non_closable_dock_close_event_blocked(self, layout_env):
        mgr, win, panels = layout_env
        w = _make_panel("toolbar")
        mgr.register("toolbar", lambda: w, closable=False)
        mgr._tree.root = insert_panel(mgr._tree.root, "toolbar")
        mgr._rebuild()
        _process()

        mgr.set_mode(MODE_EDIT)
        _process()

        entry = mgr._panels["toolbar"]
        assert entry.dock_widget is not None
        features = entry.dock_widget.features()
        assert not (features & QtWidgets.QDockWidget.DockWidgetClosable)

    def test_non_closable_floating_close_blocked(self, layout_env):
        mgr, win, panels = layout_env
        w = _make_panel("toolbar")
        mgr.register("toolbar", lambda: w, closable=False)
        mgr.toggle_panel("toolbar")
        _process()

        assert "toolbar" in mgr._tree.floating
        mgr.toggle_panel("toolbar")
        _process()
        assert "toolbar" in mgr._tree.floating

    def test_closable_panel_can_be_toggled_off(self, layout_env):
        mgr, win, panels = layout_env
        assert mgr.is_panel_visible("folder")
        mgr.toggle_panel("folder")
        _process()
        assert mgr.is_panel_collapsed("folder")


class TestDynamicToggleCommands:
    def test_register_creates_toggle_command(self, layout_env):
        mgr, win, panels = layout_env
        from wafer.core.commands.command.core import CommandRegistry

        reg = CommandRegistry.instance()
        assert reg.has_command("panel.toggle_folder")
        assert reg.has_command("panel.toggle_grid")
        assert reg.has_command("panel.toggle_viewer")

    def test_unregister_removes_toggle_command(self, layout_env):
        mgr, win, panels = layout_env
        from wafer.core.commands.command.core import CommandRegistry

        reg = CommandRegistry.instance()
        assert reg.has_command("panel.toggle_viewer")
        mgr.unregister("viewer")
        _process()
        assert not reg.has_command("panel.toggle_viewer")

    def test_toggle_command_id_slugifies_spaces(self, layout_env):
        mgr, win, panels = layout_env
        w = _make_panel("File Viewer")
        mgr.register("File Viewer", lambda: w)
        from wafer.core.commands.command.core import CommandRegistry

        reg = CommandRegistry.instance()
        assert reg.has_command("panel.toggle_file_viewer")

    def test_command_id_generation(self, layout_env):
        mgr, win, panels = layout_env
        assert mgr._command_id("Folder Tree") == "panel.toggle_folder_tree"
        assert mgr._command_id("Grid View") == "panel.toggle_grid_view"
        assert mgr._command_id("Search") == "panel.toggle_search"


class TestDeferredRestore:
    @pytest.fixture()
    def five_panel_state(self):
        return {
            "mode": "locked",
            "tree": {
                "root": {
                    "type": "split",
                    "orientation": "horizontal",
                    "sizes": [200, 600, 400],
                    "children": [
                        {
                            "type": "split",
                            "orientation": "vertical",
                            "sizes": [80, 500],
                            "children": [
                                {"type": "leaf", "panel": "Toolbar"},
                                {"type": "leaf", "panel": "Folder Tree"},
                            ],
                        },
                        {
                            "type": "split",
                            "orientation": "vertical",
                            "sizes": [40, 540],
                            "children": [
                                {"type": "leaf", "panel": "Search"},
                                {"type": "leaf", "panel": "Grid View"},
                            ],
                        },
                        {"type": "leaf", "panel": "File Viewer"},
                    ],
                },
                "floating": {},
                "collapsed": [],
            },
        }

    def test_late_register_docked_panel_appears(self, qapp, five_panel_state):
        win = QtWidgets.QMainWindow()
        win.show()
        mgr = LayoutManager(win)
        mgr.register("Toolbar", lambda: _make_panel("Toolbar"), closable=False)
        mgr.register("Folder Tree", lambda: _make_panel("Folder Tree"))
        mgr.register("Search", lambda: _make_panel("Search"))
        mgr.restore_state(five_panel_state)
        qapp.processEvents()

        assert "Grid View" not in mgr._tree.all_names()

        mgr.register("Grid View", lambda: _make_panel("Grid View"))
        qapp.processEvents()

        assert "Grid View" in mgr._tree.docked_names()
        assert mgr._panels["Grid View"].widget is not None

    def test_late_register_preserves_tree_order(self, qapp, five_panel_state):
        win = QtWidgets.QMainWindow()
        win.show()
        mgr = LayoutManager(win)
        mgr.register("Toolbar", lambda: _make_panel("Toolbar"), closable=False)
        mgr.register("Folder Tree", lambda: _make_panel("Folder Tree"))
        mgr.register("Search", lambda: _make_panel("Search"))
        mgr.restore_state(five_panel_state)
        qapp.processEvents()

        mgr.register("Grid View", lambda: _make_panel("Grid View"))
        mgr.register("File Viewer", lambda: _make_panel("File Viewer"))
        qapp.processEvents()

        names = mgr._tree.docked_names()
        assert names.index("Search") < names.index("Grid View")
        assert names.index("Grid View") < names.index("File Viewer")
        assert names.index("Toolbar") < names.index("Folder Tree")

    def test_late_register_floating_panel(self, qapp):
        state = {
            "mode": "locked",
            "tree": {
                "root": {"type": "leaf", "panel": "A"},
                "floating": {"B": {"x": 100, "y": 200, "width": 300, "height": 250}},
                "collapsed": [],
            },
        }
        win = QtWidgets.QMainWindow()
        win.show()
        mgr = LayoutManager(win)
        mgr.register("A", lambda: _make_panel("A"))
        mgr.restore_state(state)
        qapp.processEvents()

        mgr.register("B", lambda: _make_panel("B"))
        qapp.processEvents()

        assert mgr._panels["B"].floating_window is not None
        geo = mgr._panels["B"].floating_window.geometry()
        assert geo.x() == 100
        assert geo.y() == 200

    def test_late_register_dormant_panel(self, qapp):
        state = {
            "mode": "locked",
            "tree": {
                "root": {"type": "leaf", "panel": "A"},
                "floating": {},
                "collapsed": [],
            },
            "dormant": {"B": {"x": 50, "y": 60, "width": 200, "height": 150}},
        }
        win = QtWidgets.QMainWindow()
        win.show()
        mgr = LayoutManager(win)
        mgr.register("A", lambda: _make_panel("A"))
        mgr.restore_state(state)
        qapp.processEvents()

        mgr.register("B", lambda: _make_panel("B"))
        qapp.processEvents()

        entry = mgr._panels["B"]
        assert entry.floating_window is None
        assert entry.dock_widget is None
        assert entry.last_floating is not None
        assert entry.last_floating.x == 50

    def test_late_register_collapsed_panel(self, qapp, five_panel_state):
        five_panel_state["tree"]["collapsed"] = ["Grid View"]
        win = QtWidgets.QMainWindow()
        win.show()
        mgr = LayoutManager(win)
        mgr.register("Toolbar", lambda: _make_panel("Toolbar"), closable=False)
        mgr.register("Folder Tree", lambda: _make_panel("Folder Tree"))
        mgr.register("Search", lambda: _make_panel("Search"))
        mgr.register("File Viewer", lambda: _make_panel("File Viewer"))
        mgr.restore_state(five_panel_state)
        qapp.processEvents()

        mgr.register("Grid View", lambda: _make_panel("Grid View"))
        qapp.processEvents()

        assert "Grid View" in mgr._tree.docked_names()
        assert "Grid View" in mgr._tree.collapsed

    def test_no_pending_without_restore(self, qapp):
        win = QtWidgets.QMainWindow()
        win.show()
        mgr = LayoutManager(win)
        mgr.register("A", lambda: _make_panel("A"))
        assert mgr._pending_state is None
        assert "A" not in mgr._tree.all_names()


class TestToggleCommandCheckable:
    def test_register_creates_checkable_command(self, layout_env):
        from wafer.core.commands.command.core import CommandRegistry
        mgr, win, panels = layout_env
        cmd_id = LayoutManager._command_id("folder")
        registry = CommandRegistry.instance()
        cmd_cls = registry.get_command(cmd_id)
        assert cmd_cls is not None
        assert cmd_cls.meta.checkable is True

    def test_resolver_returns_true_for_docked_panel(self, layout_env):
        from wafer.core.commands.command.core import CommandRegistry
        mgr, win, panels = layout_env
        cmd_id = LayoutManager._command_id("folder")
        cmd_cls = CommandRegistry.instance().get_command(cmd_id)
        assert cmd_cls.meta.checked is not None
        assert cmd_cls.meta.checked() is True

    def test_resolver_returns_true_for_collapsed_panel(self, layout_env):
        from wafer.core.commands.command.core import CommandRegistry
        mgr, win, panels = layout_env
        _process(10)
        mgr.toggle_panel("viewer")
        _process()
        assert mgr.is_panel_collapsed("viewer")

        cmd_id = LayoutManager._command_id("viewer")
        cmd_cls = CommandRegistry.instance().get_command(cmd_id)
        assert cmd_cls.meta.checked() is True

    def test_resolver_returns_true_for_floating_panel(self, layout_env):
        from wafer.core.commands.command.core import CommandRegistry
        mgr, win, panels = layout_env
        w = _make_panel("dyn")
        _register_floating(mgr, "dyn", w)
        _process()

        cmd_id = LayoutManager._command_id("dyn")
        cmd_cls = CommandRegistry.instance().get_command(cmd_id)
        assert cmd_cls.meta.checked() is True

    def test_resolver_returns_false_for_dormant_panel(self, layout_env):
        from wafer.core.commands.command.core import CommandRegistry
        mgr, win, panels = layout_env
        w = _make_panel("dyn")
        _register_floating(mgr, "dyn", w)
        _process()

        mgr.toggle_panel("dyn")
        _process()
        assert "dyn" in mgr.dormant_panels()

        cmd_id = LayoutManager._command_id("dyn")
        cmd_cls = CommandRegistry.instance().get_command(cmd_id)
        assert cmd_cls.meta.checked() is False

    def test_resolver_tracks_state_changes_dynamically(self, layout_env):
        from wafer.core.commands.command.core import CommandRegistry
        mgr, win, panels = layout_env
        w = _make_panel("dyn")
        _register_floating(mgr, "dyn", w)
        _process()

        cmd_id = LayoutManager._command_id("dyn")
        cmd_cls = CommandRegistry.instance().get_command(cmd_id)
        assert cmd_cls.meta.checked() is True

        mgr.toggle_panel("dyn")
        _process()
        assert cmd_cls.meta.checked() is False

        mgr.toggle_panel("dyn")
        _process()
        assert cmd_cls.meta.checked() is True


class TestResetToDefault:
    def test_reset_relocates_default_external_floating(self, layout_env):
        mgr, win, panels = layout_env
        w = _make_panel("dyn")
        _register_floating(mgr, "dyn", w)
        _process()

        entry = mgr._panels["dyn"]
        assert entry.floating_window is not None
        entry.floating_window.setGeometry(5000, 5000, 400, 300)
        _process()

        mgr.reset_to_default(_DEFAULT_STATE)
        _process()

        assert entry.floating_window is not None
        assert "dyn" in mgr._tree.floating

        geo = win.geometry()
        fs = mgr._tree.floating["dyn"]
        assert fs.x == geo.x() + geo.width() // 2 - 200
        assert fs.y == geo.y() + geo.height() // 2 - 150

    def test_reset_returns_floated_default_panel_to_dock(self, layout_env):
        mgr, win, panels = layout_env
        mgr.set_mode(MODE_EDIT)
        _process()
        mgr._panels["viewer"].dock_widget.close()
        _process()
        mgr.set_mode(MODE_LOCKED)
        _process()
        mgr.toggle_panel("viewer")
        _process()
        assert mgr._panels["viewer"].floating_window is not None
        assert "viewer" in mgr._tree.floating

        mgr.reset_to_default(_DEFAULT_STATE)
        _process()

        assert mgr._panels["viewer"].floating_window is None
        assert "viewer" not in mgr._tree.floating
        assert "viewer" in set(mgr._tree.docked_names())
        assert mgr.is_panel_visible("viewer")

    def test_reset_clears_last_floating(self, layout_env):
        mgr, win, panels = layout_env
        w = _make_panel("dyn")
        _register_floating(mgr, "dyn", w)
        _process()
        mgr._panels["dyn"].floating_window.setGeometry(5000, 5000, 400, 300)
        _process()

        mgr.toggle_panel("dyn")
        _process()
        assert mgr._panels["dyn"].last_floating.x == 5000

        mgr.reset_to_default(_DEFAULT_STATE)
        _process()

        assert mgr._panels["dyn"].last_floating is None

    def test_reset_cascades_multiple_external_floating(self, layout_env):
        mgr, win, panels = layout_env
        wa = _make_panel("dyn_a")
        wb = _make_panel("dyn_b")
        _register_floating(mgr, "dyn_a", wa)
        _register_floating(mgr, "dyn_b", wb)
        _process()

        mgr.reset_to_default(_DEFAULT_STATE)
        _process()

        assert "dyn_a" in mgr._tree.floating
        assert "dyn_b" in mgr._tree.floating
        fa = mgr._tree.floating["dyn_a"]
        fb = mgr._tree.floating["dyn_b"]
        assert (fa.x, fa.y) != (fb.x, fb.y)

    def test_reset_keeps_main_window_geometry(self, layout_env):
        mgr, win, panels = layout_env
        w = _make_panel("dyn")
        _register_floating(mgr, "dyn", w)
        _process()

        before = win.geometry()
        mgr.reset_to_default(_DEFAULT_STATE)
        _process()
        after = win.geometry()

        assert before == after


class TestResetFloatingPositions:
    def _cascade_origin(self, win, step=0):
        geo = win.geometry()
        cx = geo.x() + geo.width() // 2 - 200 + step * 30
        cy = geo.y() + geo.height() // 2 - 150 + step * 30
        return cx, cy

    def test_reposition_keeps_size(self, layout_env):
        mgr, win, panels = layout_env
        _register_floating(mgr, "dyn", _make_panel("dyn"))
        _process()

        entry = mgr._panels["dyn"]
        entry.floating_window.setGeometry(5000, 5000, 640, 480)
        _process()
        before = entry.floating_window.geometry()

        count = mgr.reset_floating_positions()
        _process()

        assert count == 1
        fs = mgr._tree.floating["dyn"]
        assert (fs.x, fs.y) == self._cascade_origin(win)
        assert (fs.width, fs.height) == (before.width(), before.height())

    def test_cascade_multiple_distinct_positions(self, layout_env):
        mgr, win, panels = layout_env
        _register_floating(mgr, "dyn_a", _make_panel("dyn_a"))
        _register_floating(mgr, "dyn_b", _make_panel("dyn_b"))
        _process()

        mgr.reset_floating_positions()
        _process()

        fa = mgr._tree.floating["dyn_a"]
        fb = mgr._tree.floating["dyn_b"]
        assert (fa.x, fa.y) != (fb.x, fb.y)

    def test_dormant_position_reset_keeps_size(self, layout_env):
        mgr, win, panels = layout_env
        _register_floating(mgr, "dyn", _make_panel("dyn"))
        _process()
        mgr._panels["dyn"].floating_window.setGeometry(5000, 5000, 640, 480)
        _process()

        mgr.toggle_panel("dyn")
        _process()
        lf_before = mgr._panels["dyn"].last_floating
        assert lf_before is not None

        count = mgr.reset_floating_positions()
        _process()

        assert count == 1
        lf = mgr._panels["dyn"].last_floating
        assert (lf.x, lf.y) == self._cascade_origin(win)
        assert (lf.width, lf.height) == (lf_before.width, lf_before.height)

    def test_no_floating_returns_zero(self, layout_env):
        mgr, win, panels = layout_env
        _process()

        assert mgr.reset_floating_positions() == 0

    def test_docked_tree_unchanged(self, layout_env):
        mgr, win, panels = layout_env
        _register_floating(mgr, "dyn", _make_panel("dyn"))
        _process()

        before_docked = set(mgr._tree.docked_names())
        before_sizes = _get_splitter_sizes(mgr)

        mgr.reset_floating_positions()
        _process()

        assert set(mgr._tree.docked_names()) == before_docked
        assert _get_splitter_sizes(mgr) == before_sizes
