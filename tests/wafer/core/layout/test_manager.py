import pytest

from PySide6 import QtCore, QtWidgets

from wafer.core.layout.manager import LayoutManager, MODE_EDIT, MODE_LOCKED, PanelEntry
from wafer.core.layout.tree import FloatingState, LayoutTree, LeafNode, Orientation, SplitNode, insert_panel


def _make_panel(name: str) -> QtWidgets.QWidget:
    w = QtWidgets.QWidget()
    w.setMinimumSize(50, 50)
    w.setObjectName(f"panel_{name}")
    return w


_DEFAULT_STATE = {
    'mode': MODE_LOCKED,
    'tree': {
        'root': {
            'type': 'split',
            'orientation': 'horizontal',
            'children': [
                {'type': 'leaf', 'panel': 'folder'},
                {'type': 'leaf', 'panel': 'grid'},
                {'type': 'leaf', 'panel': 'viewer'},
            ],
            'sizes': [200, 400, 400],
        },
        'floating': {},
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


class TestToggleEditMode:
    def test_toggle_docked_in_edit_makes_dormant(self, layout_env):
        mgr, win, panels = layout_env
        mgr.set_mode(MODE_EDIT)
        _process()

        mgr.toggle_panel("viewer")
        _process()

        assert mgr.mode == MODE_EDIT
        assert "viewer" in mgr.dormant_panels()

    def test_toggle_dormant_in_edit_shows_floating(self, layout_env):
        mgr, win, panels = layout_env
        mgr.set_mode(MODE_EDIT)
        _process()

        mgr.toggle_panel("viewer")
        _process()
        assert "viewer" in mgr.dormant_panels()

        mgr.toggle_panel("viewer")
        _process()

        assert mgr.mode == MODE_EDIT
        assert mgr.is_panel_visible("viewer")
        entry = mgr._panels["viewer"]
        assert entry.dock_widget is not None


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
        assert 'mode' in state
        assert 'tree' in state
        assert state['mode'] == MODE_LOCKED

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
        assert state['mode'] == MODE_EDIT

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
        assert "viewer" in state.get('dormant', {})

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
        tree_dict = state['tree']

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
            'mode': MODE_LOCKED,
            'tree': {
                'root': {
                    'type': 'split',
                    'orientation': 'horizontal',
                    'children': [
                        {'type': 'leaf', 'panel': 'folder'},
                        {'type': 'leaf', 'panel': 'grid'},
                        {'type': 'leaf', 'panel': 'viewer'},
                        {'type': 'leaf', 'panel': 'ghost_panel'},
                    ],
                    'sizes': [100, 200, 300, 400],
                },
                'floating': {},
            },
        }

        mgr.restore_state(state_dict)
        _process()

        assert "ghost_panel" not in set(mgr._tree.docked_names())

    def test_restore_filters_unregistered_floating(self, layout_env):
        mgr, win, panels = layout_env

        state_dict = {
            'mode': MODE_LOCKED,
            'tree': {
                'root': {
                    'type': 'split',
                    'orientation': 'horizontal',
                    'children': [
                        {'type': 'leaf', 'panel': 'folder'},
                        {'type': 'leaf', 'panel': 'grid'},
                        {'type': 'leaf', 'panel': 'viewer'},
                    ],
                    'sizes': [100, 200, 300],
                },
                'floating': {
                    'ghost_float': {'x': 0, 'y': 0, 'width': 100, 'height': 100},
                },
            },
        }

        mgr.restore_state(state_dict)
        _process()

        assert "ghost_float" not in mgr._tree.floating

    def test_restore_filters_unregistered_collapsed(self, layout_env):
        mgr, win, panels = layout_env

        state_dict = {
            'mode': MODE_LOCKED,
            'tree': {
                'root': {
                    'type': 'split',
                    'orientation': 'horizontal',
                    'children': [
                        {'type': 'leaf', 'panel': 'folder'},
                        {'type': 'leaf', 'panel': 'grid'},
                        {'type': 'leaf', 'panel': 'viewer'},
                    ],
                    'sizes': [100, 200, 300],
                },
                'floating': {},
                'collapsed': ['ghost_panel', 'viewer'],
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
            'mode': MODE_LOCKED,
            'tree': {
                'root': {
                    'type': 'split',
                    'orientation': 'horizontal',
                    'children': [
                        {'type': 'leaf', 'panel': 'folder'},
                        {'type': 'leaf', 'panel': 'grid'},
                        {'type': 'leaf', 'panel': 'viewer'},
                    ],
                    'sizes': [100, 200, 300],
                },
                'floating': {},
                'collapsed': [],
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
            'mode': MODE_LOCKED,
            'tree': {
                'root': {
                    'type': 'split',
                    'orientation': 'horizontal',
                    'children': [
                        {'type': 'leaf', 'panel': 'folder'},
                        {'type': 'leaf', 'panel': 'grid'},
                        {'type': 'leaf', 'panel': 'viewer'},
                    ],
                    'sizes': [100, 200, 300],
                },
                'floating': {},
                'collapsed': [],
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
            'mode': MODE_EDIT,
            'tree': mgr.save_state()['tree'],
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
