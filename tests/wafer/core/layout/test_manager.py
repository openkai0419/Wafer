import pytest

from PySide6 import QtCore, QtWidgets

from wafer.core.layout.manager import LayoutManager, MODE_EDIT, MODE_LOCKED, PanelEntry
from wafer.core.layout.tree import FloatingState, LayoutTree, LeafNode, Orientation, SplitNode


def _make_panel(name: str) -> QtWidgets.QWidget:
    w = QtWidgets.QWidget()
    w.setMinimumSize(50, 50)
    w.setObjectName(f"panel_{name}")
    return w


@pytest.fixture
def layout_env(qtbot):
    win = QtWidgets.QMainWindow()
    win.resize(1200, 700)
    qtbot.addWidget(win)
    win.show()
    qtbot.waitExposed(win)

    mgr = LayoutManager(win)
    panels = {}
    for name, area in [
        ("folder", QtCore.Qt.LeftDockWidgetArea),
        ("grid", QtCore.Qt.LeftDockWidgetArea),
        ("viewer", QtCore.Qt.RightDockWidgetArea),
    ]:
        w = _make_panel(name)
        panels[name] = w
        mgr.register(name, w, name.title(), floating=False, default_area=area)

    mgr.set_mode(MODE_LOCKED)
    QtWidgets.QApplication.processEvents()
    return mgr, win, panels


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
            assert mgr.is_panel_visible(name)

    def test_docked_names_stable_after_roundtrip(self, layout_env):
        mgr, win, panels = layout_env
        initial_docked = set(mgr._tree.docked_names())

        mgr.set_mode(MODE_EDIT)
        _process()
        mgr.set_mode(MODE_LOCKED)
        _process()

        assert set(mgr._tree.docked_names()) == initial_docked


class TestFloatingWindowTracking:
    def test_float_in_locked_mode_creates_window(self, layout_env):
        mgr, win, panels = layout_env
        mgr.float_panel("viewer")
        _process()

        entry = mgr._panels["viewer"]
        assert entry.floating_window is not None
        assert "viewer" in mgr._tree.floating
        assert "viewer" not in set(mgr._tree.docked_names())

    def test_floating_survives_lock_to_edit(self, layout_env):
        mgr, win, panels = layout_env
        mgr.float_panel("viewer")
        _process()

        mgr.set_mode(MODE_EDIT)
        _process()

        entry = mgr._panels["viewer"]
        assert mgr.is_panel_visible("viewer")
        assert entry.dock_widget is not None
        assert entry.dock_widget.isFloating()
        assert "viewer" in mgr._tree.floating

    def test_floating_survives_lock_edit_lock(self, layout_env):
        mgr, win, panels = layout_env
        mgr.float_panel("viewer")
        _process()

        mgr.set_mode(MODE_EDIT)
        _process()
        mgr.set_mode(MODE_LOCKED)
        _process()

        entry = mgr._panels["viewer"]
        assert mgr.is_panel_visible("viewer")
        assert entry.floating_window is not None
        assert "viewer" in mgr._tree.floating

    def test_floating_survives_many_toggles(self, layout_env):
        mgr, win, panels = layout_env
        mgr.float_panel("viewer")
        _process()

        for _ in range(6):
            mgr.toggle_mode()
            _process()

        assert mgr.is_panel_visible("viewer")
        assert "viewer" in mgr._tree.floating

    def test_dock_back_removes_from_floating(self, layout_env):
        mgr, win, panels = layout_env
        mgr.float_panel("viewer")
        _process()
        mgr.dock_panel("viewer")
        _process()

        assert "viewer" not in mgr._tree.floating
        assert "viewer" in set(mgr._tree.docked_names())

    def test_floating_not_hidden_after_mode_switch(self, layout_env):
        mgr, win, panels = layout_env
        mgr.float_panel("viewer")
        _process()

        mgr.set_mode(MODE_EDIT)
        _process()

        assert "viewer" not in mgr._tree.hidden


class TestDynamicPanels:
    def test_dynamic_panel_registers_floating(self, layout_env):
        mgr, win, panels = layout_env
        w = _make_panel("dynamic_1")
        mgr.register("dynamic_1", w, "Dynamic 1", floating=True)
        _process()

        assert "dynamic_1" in mgr.panel_names()
        assert "dynamic_1" in mgr._tree.floating

    def test_dynamic_panel_survives_mode_switch(self, layout_env):
        mgr, win, panels = layout_env
        w = _make_panel("dynamic_1")
        mgr.register("dynamic_1", w, "Dynamic 1", floating=True)
        _process()

        mgr.set_mode(MODE_EDIT)
        _process()
        mgr.set_mode(MODE_LOCKED)
        _process()

        assert mgr.is_panel_visible("dynamic_1")
        assert "dynamic_1" in mgr._tree.floating

    def test_dynamic_docked_then_mode_switch(self, layout_env):
        mgr, win, panels = layout_env
        w = _make_panel("dynamic_1")
        mgr.register("dynamic_1", w, "Dynamic 1", floating=True)
        _process()

        mgr.dock_panel("dynamic_1")
        _process()

        assert "dynamic_1" in set(mgr._tree.docked_names())
        assert "dynamic_1" not in mgr._tree.floating

        mgr.set_mode(MODE_EDIT)
        _process()

        assert mgr.is_panel_visible("dynamic_1")
        entry = mgr._panels["dynamic_1"]
        assert entry.dock_widget is not None

    def test_dynamic_panel_in_edit_mode(self, layout_env):
        mgr, win, panels = layout_env
        mgr.set_mode(MODE_EDIT)
        _process()

        w = _make_panel("dynamic_1")
        mgr.register("dynamic_1", w, "Dynamic 1", floating=True)
        _process()

        assert mgr.is_panel_visible("dynamic_1")
        entry = mgr._panels["dynamic_1"]
        assert entry.dock_widget is not None
        assert entry.dock_widget.isFloating()

    def test_unregister_removes_panel(self, layout_env):
        mgr, win, panels = layout_env
        w = _make_panel("dynamic_1")
        mgr.register("dynamic_1", w, "Dynamic 1", floating=True)
        _process()

        mgr.unregister("dynamic_1")
        _process()

        assert "dynamic_1" not in mgr.panel_names()
        assert "dynamic_1" not in mgr._tree.floating


class TestTogglePanel:
    def test_toggle_hides_in_locked(self, layout_env):
        mgr, win, panels = layout_env
        mgr.toggle_panel("viewer")
        _process()

        assert not mgr.is_panel_visible("viewer")
        assert "viewer" in mgr._tree.hidden

    def test_toggle_restores_in_locked(self, layout_env):
        mgr, win, panels = layout_env
        mgr.toggle_panel("viewer")
        _process()
        mgr.toggle_panel("viewer")
        _process()

        assert mgr.is_panel_visible("viewer")
        assert "viewer" not in mgr._tree.hidden

    def test_toggle_hides_in_edit(self, layout_env):
        mgr, win, panels = layout_env
        mgr.set_mode(MODE_EDIT)
        _process()

        mgr.toggle_panel("viewer")
        _process()

        assert not mgr.is_panel_visible("viewer")

    def test_toggle_restores_in_edit(self, layout_env):
        mgr, win, panels = layout_env
        mgr.set_mode(MODE_EDIT)
        _process()

        mgr.toggle_panel("viewer")
        _process()
        mgr.toggle_panel("viewer")
        _process()

        assert mgr.is_panel_visible("viewer")


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
        mgr.float_panel("viewer")
        _process()

        state = mgr.save_state()

        mgr.dock_panel("viewer")
        _process()

        mgr.restore_state(state)
        _process()

        assert mgr.mode == MODE_LOCKED
        assert "viewer" in mgr._tree.floating

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

    def test_save_restore_roundtrip_tree(self, layout_env):
        mgr, win, panels = layout_env
        mgr.float_panel("viewer")
        mgr.toggle_panel("folder")
        _process()

        state = mgr.save_state()
        tree_dict = state['tree']

        restored_tree = LayoutTree.from_dict(tree_dict)
        assert "viewer" in restored_tree.floating
        assert "folder" in restored_tree.hidden


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

    def test_edit_mode_floating_is_dock_widget(self, layout_env):
        mgr, win, panels = layout_env
        mgr.set_mode(MODE_EDIT)
        _process()

        mgr.float_panel("viewer")
        _process()

        entry = mgr._panels["viewer"]
        assert entry.dock_widget is not None
        assert entry.dock_widget.isFloating()
        assert entry.floating_window is None


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
