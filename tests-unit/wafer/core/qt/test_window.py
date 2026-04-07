import base64
from unittest.mock import MagicMock, PropertyMock, patch

import pytest
from PySide6 import QtCore, QtWidgets

from wafer.core.qt.window import WindowSnapshot, WindowStateController

WS = QtCore.Qt.WindowState


def _wait_state(qtbot, win, check, timeout=3000):
    qtbot.waitUntil(check, timeout=timeout)
    QtWidgets.QApplication.processEvents()


def _has_frame(win):
    return not bool(win.windowFlags() & QtCore.Qt.FramelessWindowHint)


class TestWindowSnapshot:
    def test_captures_state_and_geometry(self, qtbot):
        w = QtWidgets.QMainWindow()
        qtbot.addWidget(w)
        w.show()
        qtbot.waitExposed(w)
        snap = WindowSnapshot(w)
        assert snap.state == w.windowState()
        assert snap.geometry == w.normalGeometry()

    def test_apply_restores_geometry(self, qtbot):
        w = QtWidgets.QMainWindow()
        qtbot.addWidget(w)
        w.resize(400, 300)
        w.move(100, 100)
        w.show()
        qtbot.waitExposed(w)
        snap = WindowSnapshot(w)
        w.resize(800, 600)
        snap.apply(w)
        assert w.normalGeometry() == snap.geometry


class TestWindowStateController:
    @pytest.fixture
    def win(self, qtbot):
        w = QtWidgets.QMainWindow()
        qtbot.addWidget(w)
        w.resize(600, 400)
        w.show()
        qtbot.waitExposed(w)
        return w

    @pytest.fixture
    def ctrl(self, win):
        return WindowStateController(win)

    def test_is_fullscreen_default(self, ctrl):
        assert ctrl.is_fullscreen is False

    def test_is_always_on_top_default(self, ctrl):
        assert ctrl.is_always_on_top is False

    def test_toggle_fullscreen_enters(self, ctrl, win, qtbot):
        ctrl.toggle_fullscreen()
        _wait_state(qtbot, win, lambda: ctrl.is_fullscreen)
        assert ctrl.is_fullscreen

    def test_toggle_fullscreen_exits_cleanly(self, ctrl, win, qtbot):
        original_state = win.windowState()
        ctrl.toggle_fullscreen()
        _wait_state(qtbot, win, lambda: ctrl.is_fullscreen)
        ctrl.toggle_fullscreen()
        _wait_state(qtbot, win, lambda: not ctrl.is_fullscreen)
        assert not ctrl.is_fullscreen
        assert win.windowState() == original_state
        assert _has_frame(win)

    def test_toggle_fullscreen_restores_geometry(self, ctrl, win, qtbot):
        original_geo = win.normalGeometry()
        ctrl.toggle_fullscreen()
        _wait_state(qtbot, win, lambda: ctrl.is_fullscreen)
        ctrl.toggle_fullscreen()
        _wait_state(qtbot, win, lambda: not ctrl.is_fullscreen)
        assert win.normalGeometry() == original_geo

    def test_toggle_fullscreen_rapid_cycle(self, ctrl, win, qtbot):
        original_geo = win.normalGeometry()
        original_state = win.windowState()
        for _ in range(5):
            ctrl.toggle_fullscreen()
            _wait_state(qtbot, win, lambda: ctrl.is_fullscreen)
            assert ctrl.is_fullscreen
            ctrl.toggle_fullscreen()
            _wait_state(qtbot, win, lambda: not ctrl.is_fullscreen)
            assert not ctrl.is_fullscreen
            assert win.windowState() == original_state
            assert _has_frame(win)
        assert win.normalGeometry() == original_geo

    def test_toggle_fullscreen_from_maximized(self, ctrl, win, qtbot):
        win.showMaximized()
        _wait_state(qtbot, win, lambda: win.isMaximized())
        ctrl.toggle_fullscreen()
        _wait_state(qtbot, win, lambda: ctrl.is_fullscreen)
        assert ctrl.is_fullscreen
        ctrl.toggle_fullscreen()
        _wait_state(qtbot, win, lambda: not ctrl.is_fullscreen)
        assert not ctrl.is_fullscreen
        assert win.isMaximized()
        assert _has_frame(win)

    def test_toggle_fullscreen_without_snap_uses_show_normal(self, ctrl, win, qtbot):
        ctrl.toggle_fullscreen()
        _wait_state(qtbot, win, lambda: ctrl.is_fullscreen)
        ctrl._pre_fullscreen_snap = None
        ctrl.toggle_fullscreen()
        _wait_state(qtbot, win, lambda: not ctrl.is_fullscreen)
        assert not ctrl.is_fullscreen
        assert _has_frame(win)

    def test_set_always_on_top_on(self, ctrl, win):
        ctrl.set_always_on_top(True)
        assert ctrl.is_always_on_top

    def test_set_always_on_top_off(self, ctrl, win):
        ctrl.set_always_on_top(True)
        ctrl.set_always_on_top(False)
        assert not ctrl.is_always_on_top

    def test_set_always_on_top_preserves_normal(self, ctrl, win):
        original_state = win.windowState()
        ctrl.set_always_on_top(True)
        assert not ctrl.is_fullscreen
        assert win.isVisible()
        assert _has_frame(win)
        assert win.windowState() == original_state

    def test_set_always_on_top_preserves_fullscreen(self, ctrl, win, qtbot):
        ctrl.toggle_fullscreen()
        _wait_state(qtbot, win, lambda: ctrl.is_fullscreen)
        ctrl.set_always_on_top(True)
        assert ctrl.is_fullscreen
        assert ctrl.is_always_on_top

    def test_set_always_on_top_preserves_maximized(self, ctrl, win, qtbot):
        win.showMaximized()
        _wait_state(qtbot, win, lambda: win.isMaximized())
        ctrl.set_always_on_top(True)
        assert ctrl.is_always_on_top
        assert win.isMaximized()
        assert _has_frame(win)

    def test_always_on_top_toggle_cycle_in_normal(self, ctrl, win):
        original_state = win.windowState()
        for _ in range(5):
            ctrl.set_always_on_top(True)
            assert ctrl.is_always_on_top
            ctrl.set_always_on_top(False)
            assert not ctrl.is_always_on_top
        assert win.windowState() == original_state
        assert _has_frame(win)

    def test_fullscreen_then_on_top_then_exit_fullscreen(self, ctrl, win, qtbot):
        ctrl.toggle_fullscreen()
        _wait_state(qtbot, win, lambda: ctrl.is_fullscreen)
        ctrl.set_always_on_top(True)
        assert ctrl.is_fullscreen
        assert ctrl.is_always_on_top
        ctrl.toggle_fullscreen()
        _wait_state(qtbot, win, lambda: not ctrl.is_fullscreen)
        assert not ctrl.is_fullscreen
        assert ctrl.is_always_on_top
        assert _has_frame(win)

    def test_minimize_and_restore(self, ctrl, win, qtbot):
        ctrl.minimize()
        _wait_state(qtbot, win, lambda: win.isMinimized())
        assert win.isMinimized()
        ctrl.restore_or_activate()
        _wait_state(qtbot, win, lambda: not win.isMinimized())
        assert not win.isMinimized()
        assert win.isVisible()

    def test_save_and_restore_geometry(self, ctrl, win):
        state = ctrl.save_full_state()
        assert isinstance(state["geometry"], str)
        base64.b64decode(state["geometry"])
        ctrl.restore_full_state(state)

    def test_save_full_state_default(self, ctrl):
        state = ctrl.save_full_state()
        assert state["always_on_top"] is False
        assert "geometry" in state

    def test_save_full_state_with_on_top(self, ctrl):
        ctrl.set_always_on_top(True)
        state = ctrl.save_full_state()
        assert state["always_on_top"] is True

    def test_restore_full_state(self, ctrl):
        ctrl.restore_full_state({"always_on_top": True})
        assert ctrl.is_always_on_top
        ctrl.restore_full_state({"always_on_top": False})
        assert not ctrl.is_always_on_top

    def test_restore_full_state_ignores_unknown_keys(self, ctrl):
        ctrl.restore_full_state({"unknown_key": 42})
        assert not ctrl.is_always_on_top


class TestWindowStateControllerComplex:
    @pytest.fixture
    def win(self, qtbot):
        w = QtWidgets.QMainWindow()
        w.setStyleSheet("QMainWindow { background: #2b2b2b; }")
        central = QtWidgets.QWidget()
        w.setCentralWidget(central)
        QtWidgets.QVBoxLayout(central)
        dock = QtWidgets.QDockWidget("Panel", w)
        dock.setWidget(QtWidgets.QLabel("content"))
        w.addDockWidget(QtCore.Qt.LeftDockWidgetArea, dock)
        qtbot.addWidget(w)
        w.resize(800, 600)
        w.show()
        qtbot.waitExposed(w)
        return w

    @pytest.fixture
    def ctrl(self, win):
        return WindowStateController(win)

    def test_fullscreen_cycle_preserves_frame(self, ctrl, win, qtbot):
        original_state = win.windowState()
        original_geo = win.normalGeometry()
        for _ in range(5):
            ctrl.toggle_fullscreen()
            _wait_state(qtbot, win, lambda: ctrl.is_fullscreen)
            assert ctrl.is_fullscreen
            assert not _has_frame(win) or ctrl.is_fullscreen
            ctrl.toggle_fullscreen()
            _wait_state(qtbot, win, lambda: not ctrl.is_fullscreen)
            assert not ctrl.is_fullscreen
            assert _has_frame(win)
            assert win.windowState() == original_state
        assert win.normalGeometry() == original_geo

    def test_fullscreen_from_maximized_returns_maximized(self, ctrl, win, qtbot):
        win.showMaximized()
        _wait_state(qtbot, win, lambda: win.isMaximized())
        ctrl.toggle_fullscreen()
        _wait_state(qtbot, win, lambda: ctrl.is_fullscreen)
        ctrl.toggle_fullscreen()
        _wait_state(qtbot, win, lambda: not ctrl.is_fullscreen)
        assert win.isMaximized()
        assert _has_frame(win)

    def test_always_on_top_during_fullscreen_cycle(self, ctrl, win, qtbot):
        ctrl.toggle_fullscreen()
        _wait_state(qtbot, win, lambda: ctrl.is_fullscreen)
        ctrl.set_always_on_top(True)
        assert ctrl.is_fullscreen
        ctrl.toggle_fullscreen()
        _wait_state(qtbot, win, lambda: not ctrl.is_fullscreen)
        assert ctrl.is_always_on_top
        assert _has_frame(win)
        ctrl.set_always_on_top(False)
        assert not ctrl.is_always_on_top
        assert _has_frame(win)

    def test_always_on_top_cycle_preserves_state(self, ctrl, win):
        original_state = win.windowState()
        for _ in range(5):
            ctrl.set_always_on_top(True)
            ctrl.set_always_on_top(False)
        assert win.windowState() == original_state
        assert _has_frame(win)

    def test_mixed_operations_sequence(self, ctrl, win, qtbot):
        original_geo = win.normalGeometry()
        ctrl.set_always_on_top(True)
        assert _has_frame(win)
        ctrl.toggle_fullscreen()
        _wait_state(qtbot, win, lambda: ctrl.is_fullscreen)
        ctrl.set_always_on_top(False)
        assert ctrl.is_fullscreen
        ctrl.toggle_fullscreen()
        _wait_state(qtbot, win, lambda: not ctrl.is_fullscreen)
        assert not ctrl.is_fullscreen
        assert not ctrl.is_always_on_top
        assert _has_frame(win)
        assert win.normalGeometry() == original_geo
