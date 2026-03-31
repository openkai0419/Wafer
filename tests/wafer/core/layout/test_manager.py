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


class TestFloatingWindowZOrder:
    def test_floating_window_has_parent(self, layout_env):
        mgr, win, panels = layout_env
        mgr.float_panel("viewer")
        _process()

        entry = mgr._panels["viewer"]
        assert entry.floating_window is not None
        assert entry.floating_window.parent() is win

    def test_floating_window_stays_on_top_after_mode_switch(self, layout_env):
        mgr, win, panels = layout_env
        mgr.float_panel("viewer")
        _process()

        mgr.set_mode(MODE_EDIT)
        _process()
        mgr.set_mode(MODE_LOCKED)
        _process()

        entry = mgr._panels["viewer"]
        assert entry.floating_window is not None
        assert entry.floating_window.parent() is win

    def test_register_as_floating_has_parent(self, layout_env):
        mgr, win, panels = layout_env
        w = _make_panel("dynamic_1")
        mgr.register("dynamic_1", w, "Dynamic 1", floating=True)
        _process()

        entry = mgr._panels["dynamic_1"]
        assert entry.floating_window is not None
        assert entry.floating_window.parent() is win


class TestToggleFloatingPanel:
    def test_toggle_floating_hides_and_shows(self, layout_env):
        mgr, win, panels = layout_env
        mgr.float_panel("viewer")
        _process()

        entry = mgr._panels["viewer"]
        assert entry.floating_window is not None
        assert entry.floating_window.isVisible()

        mgr.toggle_panel("viewer")
        _process()
        assert not mgr.is_panel_visible("viewer")
        assert entry.floating_window is not None
        assert not entry.floating_window.isVisible()

        mgr.toggle_panel("viewer")
        _process()
        assert mgr.is_panel_visible("viewer")
        assert entry.floating_window is not None
        assert entry.floating_window.isVisible()


class TestBug1EditModeToggleUnhide:
    def test_toggle_unhide_creates_dock_in_edit(self, layout_env):
        mgr, win, panels = layout_env
        mgr.toggle_panel("viewer")
        _process()
        mgr.set_mode(MODE_EDIT)
        _process()

        entry = mgr._panels["viewer"]
        assert entry.dock_widget is None

        mgr.toggle_panel("viewer")
        _process()

        assert mgr.is_panel_visible("viewer")
        assert entry.dock_widget is not None

    def test_unhidden_dock_contains_correct_widget(self, layout_env):
        mgr, win, panels = layout_env
        mgr.toggle_panel("viewer")
        _process()
        mgr.set_mode(MODE_EDIT)
        _process()

        mgr.toggle_panel("viewer")
        _process()

        entry = mgr._panels["viewer"]
        assert entry.dock_widget.widget() is panels["viewer"]


class TestBug2HiddenPanelSizes:
    def test_hidden_panel_preserves_tree_structure(self, layout_env):
        mgr, win, panels = layout_env
        _process(10)

        mgr._sync_tree_from_current()
        root = mgr._tree.root
        assert isinstance(root, SplitNode)
        initial_child_count = len(root.children)

        mgr.toggle_panel("grid")
        _process(10)

        mgr._sync_tree_from_current()
        root = mgr._tree.root
        assert isinstance(root, SplitNode)
        assert len(root.children) == initial_child_count
        assert len(root.sizes) == len(root.children)

    def test_hidden_panel_sizes_after_roundtrip(self, layout_env):
        mgr, win, panels = layout_env
        _process(10)

        mgr.toggle_panel("grid")
        _process(10)

        mgr.set_mode(MODE_EDIT)
        _process(10)
        mgr.set_mode(MODE_LOCKED)
        _process(10)

        mgr.toggle_panel("grid")
        _process(10)

        assert mgr.is_panel_visible("grid")
        assert mgr._root_splitter is not None


class TestBug5WidgetRecovery:
    def test_unregister_floating_widget_survives(self, layout_env):
        import shiboken6
        mgr, win, panels = layout_env
        w = _make_panel("dyn")
        mgr.register("dyn", w, "Dynamic", floating=True)
        _process()

        mgr.unregister("dyn")
        _process(10)

        assert shiboken6.isValid(w)

    def test_unregister_docked_widget_survives(self, layout_env):
        import shiboken6
        mgr, win, panels = layout_env
        w = _make_panel("dyn")
        mgr.register("dyn", w, "Dynamic", floating=False)
        _process()

        mgr.unregister("dyn")
        _process(10)

        assert shiboken6.isValid(w)


class TestBug6DoubleRegister:
    def test_double_register_replaces_old(self, layout_env):
        mgr, win, panels = layout_env
        w1 = _make_panel("dyn")
        mgr.register("dyn", w1, "Dynamic 1", floating=True)
        _process()

        w2 = _make_panel("dyn")
        mgr.register("dyn", w2, "Dynamic 2", floating=True)
        _process()

        entry = mgr._panels["dyn"]
        assert entry.widget is w2
        assert entry.floating_window is not None

    def test_double_register_no_old_floating_leak(self, layout_env):
        mgr, win, panels = layout_env
        w1 = _make_panel("dyn")
        mgr.register("dyn", w1, "Dynamic 1", floating=True)
        _process()

        old_window = mgr._panels["dyn"].floating_window

        w2 = _make_panel("dyn")
        mgr.register("dyn", w2, "Dynamic 2", floating=True)
        _process()

        new_entry = mgr._panels["dyn"]
        assert new_entry.floating_window is not old_window


class TestBug8RestoreGhostEntries:
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
                'hidden': [],
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
                'hidden': ['ghost_hidden'],
            },
        }

        mgr.restore_state(state_dict)
        _process()

        assert "ghost_float" not in mgr._tree.floating
        assert "ghost_hidden" not in mgr._tree.hidden


class TestBug9RebuildEditMode:
    def test_dock_panel_in_edit_mode(self, layout_env):
        mgr, win, panels = layout_env
        mgr.set_mode(MODE_EDIT)
        _process()

        mgr.float_panel("viewer")
        _process()

        mgr.dock_panel("viewer")
        _process()

        assert "viewer" in set(mgr._tree.docked_names())
        assert "viewer" not in mgr._tree.floating
        entry = mgr._panels["viewer"]
        assert entry.dock_widget is not None

    def test_register_docked_in_edit_mode(self, layout_env):
        mgr, win, panels = layout_env
        mgr.set_mode(MODE_EDIT)
        _process()

        w = _make_panel("dyn")
        mgr.register("dyn", w, "Dynamic", floating=False)
        _process()

        entry = mgr._panels["dyn"]
        assert entry.dock_widget is not None
        assert "dyn" in set(mgr._tree.docked_names())

    def test_toggle_floating_multiple_times(self, layout_env):
        mgr, win, panels = layout_env
        mgr.float_panel("viewer")
        _process()

        for _ in range(5):
            mgr.toggle_panel("viewer")
            _process()
            assert not mgr.is_panel_visible("viewer")
            mgr.toggle_panel("viewer")
            _process()
            assert mgr.is_panel_visible("viewer")

        entry = mgr._panels["viewer"]
        assert entry.floating_window is not None
        assert entry.floating_window.isVisible()


class TestRestoreUntrackedPanels:
    def test_locked_mode_untracked_panel_shown_as_floating(self, layout_env):
        mgr, win, panels = layout_env
        state = mgr.save_state()
        _process()

        w = _make_panel("extra")
        mgr.register("extra", w, "Extra", floating=True)
        _process()

        mgr.restore_state(state)
        _process()

        entry = mgr._panels["extra"]
        assert entry.floating_window is not None
        assert entry.floating_window.isVisible()
        assert "extra" in mgr._tree.floating

    def test_edit_mode_untracked_panel_shown_as_floating(self, layout_env):
        mgr, win, panels = layout_env
        mgr.set_mode(MODE_EDIT)
        _process()
        state = mgr.save_state()
        mgr.set_mode(MODE_LOCKED)
        _process()

        w = _make_panel("extra")
        mgr.register("extra", w, "Extra", floating=True)
        _process()

        mgr.restore_state(state)
        _process()

        entry = mgr._panels["extra"]
        assert entry.dock_widget is not None
        assert entry.dock_widget.isFloating()
        assert "extra" in mgr._tree.floating

    def test_locked_mode_multiple_untracked(self, layout_env):
        mgr, win, panels = layout_env
        state = mgr.save_state()
        _process()

        for i in range(3):
            w = _make_panel(f"dyn_{i}")
            mgr.register(f"dyn_{i}", w, f"Dyn {i}", floating=True)
        _process()

        mgr.restore_state(state)
        _process()

        for i in range(3):
            name = f"dyn_{i}"
            entry = mgr._panels[name]
            assert entry.floating_window is not None
            assert name in mgr._tree.floating

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
