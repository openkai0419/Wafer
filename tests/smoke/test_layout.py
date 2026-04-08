import time

import pytest
from PySide6 import QtCore, QtWidgets

from wafer.ui.layout.manager import LayoutManager, MODE_EDIT, MODE_LOCKED, PanelEntry
from wafer.ui.layout.tree import (
    FloatingState,
    LayoutTree,
    LeafNode,
    Orientation,
    SplitNode,
)
from wafer.core.commands.command.core import CommandRegistry


def _process_events(ms=50):
    app = QtWidgets.QApplication.instance()
    if app:
        app.processEvents(QtCore.QEventLoop.AllEvents, ms)


def _process_events_until(predicate, timeout_ms=5000):
    app = QtWidgets.QApplication.instance()
    deadline = time.monotonic() + timeout_ms / 1000.0
    while not predicate() and time.monotonic() < deadline:
        app.processEvents(QtCore.QEventLoop.AllEvents, 50)
        time.sleep(0.01)


def _stub_widget(label="stub"):
    w = QtWidgets.QLabel(label)
    w.setMinimumSize(10, 10)
    return w


def _default_tree():
    return {
        "mode": "locked",
        "tree": {
            "root": {
                "type": "split",
                "orientation": "horizontal",
                "children": [
                    {"type": "leaf", "panel": "A"},
                    {
                        "type": "split",
                        "orientation": "vertical",
                        "children": [
                            {"type": "leaf", "panel": "B"},
                            {"type": "leaf", "panel": "C"},
                        ],
                        "sizes": [300, 300],
                    },
                ],
                "sizes": [200, 600],
            },
            "floating": {},
        },
    }


def _default_tree_with_d():
    state = _default_tree()
    state["tree"]["root"]["children"].append({"type": "leaf", "panel": "D"})
    state["tree"]["root"]["sizes"].append(200)
    return state


@pytest.fixture(autouse=True, scope="module")
def _configure_command_store(tmp_path_factory):
    from wafer.core.commands.command.state import CommandOptionStore

    prev = CommandOptionStore._instance, CommandOptionStore._initialized, CommandOptionStore._default_path
    CommandOptionStore._instance = None
    CommandOptionStore._initialized = False
    CommandOptionStore._default_path = None
    CommandOptionStore.configure(tmp_path_factory.mktemp("smoke_layout") / "cmd.json")
    yield
    CommandOptionStore._instance, CommandOptionStore._initialized, CommandOptionStore._default_path = prev


@pytest.fixture()
def layout_env(qtbot):
    window = QtWidgets.QMainWindow()
    window.resize(1200, 800)
    qtbot.addWidget(window)

    mgr = LayoutManager(window)
    mgr.set_margin(5)
    mgr.register("A", lambda: _stub_widget("A"))
    mgr.register("B", lambda: _stub_widget("B"))
    mgr.register("C", lambda: _stub_widget("C"))

    mgr.restore_state(_default_tree())
    window.show()
    _process_events()

    yield window, mgr

    window.close()
    _process_events()


class TestLayoutBoot:
    def test_boot_with_restore(self, layout_env):
        window, mgr = layout_env
        assert set(mgr.panel_names()) == {"A", "B", "C"}
        assert mgr.mode == MODE_LOCKED

    def test_all_panels_visible_after_restore(self, layout_env):
        window, mgr = layout_env
        for name in ["A", "B", "C"]:
            assert mgr.is_panel_visible(name)
            w = mgr.panel_widget(name)
            assert w is not None
            assert w.isVisible()

    def test_restore_empty_state(self, qtbot):
        window = QtWidgets.QMainWindow()
        window.resize(800, 600)
        qtbot.addWidget(window)
        mgr = LayoutManager(window)
        mgr.register("X", lambda: _stub_widget("X"))
        mgr.restore_state({"mode": "locked", "tree": {"root": None, "floating": {}}})
        window.show()
        _process_events()
        assert mgr.panel_widget("X") is not None
        window.close()

    def test_restore_with_missing_panel(self, qtbot):
        window = QtWidgets.QMainWindow()
        window.resize(800, 600)
        qtbot.addWidget(window)
        mgr = LayoutManager(window)
        mgr.register("A", lambda: _stub_widget("A"))
        state = _default_tree()
        mgr.restore_state(state)
        window.show()
        _process_events()
        assert mgr.is_panel_visible("A")
        assert "B" not in mgr.panel_names()
        assert "C" not in mgr.panel_names()
        window.close()


class TestModeSwitching:
    def test_locked_to_edit(self, layout_env):
        window, mgr = layout_env
        mgr.set_mode(MODE_EDIT)
        _process_events()
        assert mgr.mode == MODE_EDIT
        for name in ["A", "B", "C"]:
            w = mgr.panel_widget(name)
            assert w is not None

    def test_edit_to_locked(self, layout_env):
        window, mgr = layout_env
        mgr.set_mode(MODE_EDIT)
        _process_events()
        mgr.set_mode(MODE_LOCKED)
        _process_events()
        assert mgr.mode == MODE_LOCKED
        for name in ["A", "B", "C"]:
            assert mgr.is_panel_visible(name)

    def test_rapid_mode_switching(self, layout_env):
        window, mgr = layout_env
        for _ in range(5):
            mgr.toggle_mode()
            _process_events()
        for name in ["A", "B", "C"]:
            w = mgr.panel_widget(name)
            assert w is not None

    def test_mode_changed_signal(self, layout_env, qtbot):
        window, mgr = layout_env
        emitted = []
        mgr.mode_changed.connect(lambda m: emitted.append(m))
        mgr.set_mode(MODE_EDIT)
        _process_events()
        mgr.set_mode(MODE_LOCKED)
        _process_events()
        assert emitted == [MODE_EDIT, MODE_LOCKED]

    def test_same_mode_noop(self, layout_env):
        window, mgr = layout_env
        emitted = []
        mgr.mode_changed.connect(lambda m: emitted.append(m))
        mgr.set_mode(MODE_LOCKED)
        _process_events()
        assert emitted == []


class TestPanelToggle:
    def test_toggle_hides_and_shows(self, layout_env):
        window, mgr = layout_env
        assert mgr.is_panel_visible("B")
        mgr.toggle_panel("B")
        _process_events()
        assert not mgr.is_panel_visible("B")
        mgr.toggle_panel("B")
        _process_events()
        assert mgr.is_panel_visible("B") or "B" in mgr._tree.floating

    def test_toggle_nonexistent(self, layout_env):
        window, mgr = layout_env
        mgr.toggle_panel("NONEXISTENT")
        _process_events()

    def test_ensure_panel_visible(self, layout_env):
        window, mgr = layout_env
        mgr.toggle_panel("C")
        _process_events()
        assert not mgr.is_panel_visible("C")
        mgr.ensure_panel_visible("C")
        _process_events()
        assert mgr.is_panel_visible("C") or "C" in mgr._tree.floating

    def test_rapid_toggle(self, layout_env):
        window, mgr = layout_env
        for _ in range(6):
            mgr.toggle_panel("A")
            _process_events()
        w = mgr.panel_widget("A")
        assert w is not None


class TestPanelRegistration:
    def test_register_after_layout(self, layout_env):
        window, mgr = layout_env
        mgr.register("D", lambda: _stub_widget("D"))
        _process_events()
        assert "D" in mgr.panel_names()
        assert "D" in mgr.dormant_panels()

    def test_unregister_panel(self, layout_env):
        window, mgr = layout_env
        mgr.unregister("C")
        _process_events()
        assert "C" not in mgr.panel_names()
        assert not mgr.is_panel_visible("C")

    def test_register_unregister_cycle(self, layout_env):
        window, mgr = layout_env
        for _ in range(3):
            mgr.register("Temp", lambda: _stub_widget("Temp"))
            _process_events()
            mgr.unregister("Temp")
            _process_events()
        assert "Temp" not in mgr.panel_names()

    def test_unclosable_panel(self, qtbot):
        window = QtWidgets.QMainWindow()
        window.resize(800, 600)
        qtbot.addWidget(window)
        mgr = LayoutManager(window)
        mgr.register("Fixed", lambda: _stub_widget("Fixed"), closable=False)
        mgr.register("Other", lambda: _stub_widget("Other"))
        state = {
            "mode": "locked",
            "tree": {
                "root": {
                    "type": "split",
                    "orientation": "horizontal",
                    "children": [
                        {"type": "leaf", "panel": "Fixed"},
                        {"type": "leaf", "panel": "Other"},
                    ],
                    "sizes": [200, 600],
                },
                "floating": {},
            },
        }
        mgr.restore_state(state)
        window.show()
        _process_events()
        assert mgr.is_panel_visible("Fixed")
        window.close()


class TestSaveRestore:
    def test_roundtrip(self, layout_env):
        window, mgr = layout_env
        saved = mgr.save_state()
        assert "tree" in saved
        assert "mode" in saved

        window2 = QtWidgets.QMainWindow()
        window2.resize(1200, 800)
        mgr2 = LayoutManager(window2)
        mgr2.register("A", lambda: _stub_widget("A"))
        mgr2.register("B", lambda: _stub_widget("B"))
        mgr2.register("C", lambda: _stub_widget("C"))
        mgr2.restore_state(saved)
        _process_events()
        assert mgr2.mode == mgr.mode
        assert set(mgr2.panel_names()) == set(mgr.panel_names())
        window2.close()
        _process_events()

    def test_save_preserves_collapsed(self, layout_env):
        window, mgr = layout_env
        mgr.toggle_panel("B")
        _process_events()
        saved = mgr.save_state()
        tree_data = saved.get("tree", {})
        collapsed = set(tree_data.get("collapsed", []))
        all_names = LayoutTree.from_dict(tree_data).all_names()
        if "B" in all_names:
            assert "B" in collapsed

    def test_restore_state_with_floating(self, qtbot):
        window = QtWidgets.QMainWindow()
        window.resize(800, 600)
        qtbot.addWidget(window)
        mgr = LayoutManager(window)
        mgr.register("A", lambda: _stub_widget("A"))
        mgr.register("B", lambda: _stub_widget("B"))
        state = {
            "mode": "locked",
            "tree": {
                "root": {"type": "leaf", "panel": "A"},
                "floating": {"B": {"x": 100, "y": 100, "width": 300, "height": 200}},
            },
        }
        mgr.restore_state(state)
        window.show()
        _process_events()
        assert mgr.is_panel_visible("A")
        assert "B" in mgr._tree.floating
        window.close()
        _process_events()

    def test_restore_state_in_edit_mode(self, qtbot):
        window = QtWidgets.QMainWindow()
        window.resize(800, 600)
        qtbot.addWidget(window)
        mgr = LayoutManager(window)
        mgr.register("A", lambda: _stub_widget("A"))
        mgr.register("B", lambda: _stub_widget("B"))
        state = {
            "mode": "edit",
            "tree": {
                "root": {
                    "type": "split",
                    "orientation": "horizontal",
                    "children": [
                        {"type": "leaf", "panel": "A"},
                        {"type": "leaf", "panel": "B"},
                    ],
                    "sizes": [400, 400],
                },
                "floating": {},
            },
        }
        mgr.restore_state(state)
        window.show()
        _process_events()
        assert mgr.mode == MODE_EDIT
        window.close()
        _process_events()

    def test_restore_dormant_panels(self, qtbot):
        window = QtWidgets.QMainWindow()
        window.resize(800, 600)
        qtbot.addWidget(window)
        mgr = LayoutManager(window)
        mgr.register("A", lambda: _stub_widget("A"))
        mgr.register("B", lambda: _stub_widget("B"))
        mgr.register("C", lambda: _stub_widget("C"))
        state = {
            "mode": "locked",
            "tree": {
                "root": {
                    "type": "split",
                    "orientation": "horizontal",
                    "children": [
                        {"type": "leaf", "panel": "A"},
                        {"type": "leaf", "panel": "B"},
                    ],
                    "sizes": [400, 400],
                },
                "floating": {},
            },
            "dormant": {"C": {"x": 50, "y": 50, "width": 200, "height": 150}},
        }
        mgr.restore_state(state)
        window.show()
        _process_events()
        assert "C" in mgr.dormant_panels()
        window.close()
        _process_events()


class TestLayoutStability:
    def test_mode_switch_preserves_widgets(self, layout_env):
        window, mgr = layout_env
        widgets_before = {name: mgr.panel_widget(name) for name in mgr.panel_names()}
        mgr.set_mode(MODE_EDIT)
        _process_events()
        mgr.set_mode(MODE_LOCKED)
        _process_events()
        for name, w in widgets_before.items():
            assert mgr.panel_widget(name) is w

    def test_toggle_during_edit_mode(self, layout_env):
        window, mgr = layout_env
        mgr.set_mode(MODE_EDIT)
        _process_events()
        mgr.toggle_panel("B")
        _process_events()
        assert mgr.mode == MODE_LOCKED

    def test_stress_toggle_and_mode_switch(self, layout_env):
        window, mgr = layout_env
        for i in range(3):
            mgr.toggle_panel("A")
            _process_events()
            mgr.toggle_mode()
            _process_events()
            mgr.toggle_panel("B")
            _process_events()
            mgr.toggle_mode()
            _process_events()
        for name in mgr.panel_names():
            w = mgr.panel_widget(name)
            assert w is not None

    def test_multiple_restore_state(self, layout_env):
        window, mgr = layout_env
        state1 = _default_tree()
        state2 = {
            "mode": "locked",
            "tree": {
                "root": {
                    "type": "split",
                    "orientation": "vertical",
                    "children": [
                        {"type": "leaf", "panel": "A"},
                        {"type": "leaf", "panel": "C"},
                    ],
                    "sizes": [400, 400],
                },
                "floating": {},
            },
            "dormant": {"B": None},
        }
        for _ in range(3):
            mgr.restore_state(state1)
            _process_events()
            assert mgr.is_panel_visible("B")
            mgr.restore_state(state2)
            _process_events()
            assert "B" in mgr.dormant_panels()


class TestToggleCommands:
    def test_toggle_commands_registered(self, layout_env):
        window, mgr = layout_env
        registry = CommandRegistry.instance()
        for name in ["A", "B", "C"]:
            cmd_id = LayoutManager._command_id(name)
            assert registry.has_command(cmd_id), f"toggle command not found: {cmd_id}"

    def test_toggle_command_unregistered_on_unregister(self, layout_env):
        window, mgr = layout_env
        registry = CommandRegistry.instance()
        cmd_id = LayoutManager._command_id("C")
        assert registry.has_command(cmd_id)
        mgr.unregister("C")
        _process_events()
        assert not registry.has_command(cmd_id)
