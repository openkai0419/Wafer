from unittest.mock import patch

import pytest
from PySide6 import QtCore, QtGui, QtWidgets

from wafer.qt.commands.binding.mixins import CommandBindingMixin
from wafer.qt.commands.binding.mouse.manager import MouseStateManager
from wafer.qt.commands.binding.mouse.types import ClickType, MouseActionKey, MouseButton

LMB = QtCore.Qt.MouseButton.LeftButton
RMB = QtCore.Qt.MouseButton.RightButton
NO_BTN = QtCore.Qt.MouseButton.NoButton
NO_MOD = QtCore.Qt.KeyboardModifier.NoModifier


class _W(QtWidgets.QWidget, CommandBindingMixin):
    pass


@pytest.fixture(autouse=True)
def _reset_state():
    MouseStateManager._instance = None
    yield
    MouseStateManager._instance = None


def _event(kind, button, buttons, pos):
    p = QtCore.QPointF(*pos)
    return QtGui.QMouseEvent(kind, p, p, p, button, buttons, NO_MOD)


def _send(w, kind, button, buttons, pos=(50, 50)):
    d = w._mouse_dispatcher
    d._state._processed_events.clear()
    d.eventFilter(w, _event(kind, button, buttons, pos))


@pytest.fixture
def widget(qtbot):
    w = _W()
    qtbot.addWidget(w)
    w.resize(200, 200)
    w.init_command_binding("TestScope", use_existing_events=True)
    w._mouse_manager.clear()
    runs = []
    for button in (MouseButton.LEFT, MouseButton.RIGHT):
        w._mouse_manager.bind(MouseActionKey(button, ClickType.SINGLE), lambda event=None, b=button: runs.append(b) or True)
    return w, runs


def test_click_fires_on_release(widget):
    w, runs = widget
    with patch.object(w._mouse_dispatcher, "_find_target_widget", return_value=w):
        _send(w, QtCore.QEvent.Type.MouseButtonPress, LMB, LMB)
        _send(w, QtCore.QEvent.Type.MouseButtonRelease, LMB, NO_BTN)
    assert runs == [MouseButton.LEFT]


def test_release_after_a_drag_without_a_drag_binding_is_not_a_click(widget):
    w, runs = widget
    with patch.object(w._mouse_dispatcher, "_find_target_widget", return_value=w):
        _send(w, QtCore.QEvent.Type.MouseButtonPress, LMB, LMB)
        _send(w, QtCore.QEvent.Type.MouseMove, NO_BTN, LMB, (120, 120))
        _send(w, QtCore.QEvent.Type.MouseButtonRelease, LMB, NO_BTN, (120, 120))
    assert runs == []


def test_release_outside_any_binding_widget_uses_up_the_suppressed_click(widget):
    w, runs = widget
    MouseStateManager.instance().add_suppress_group([MouseButton.RIGHT])
    with patch.object(w._mouse_dispatcher, "_find_target_widget", return_value=None):
        _send(w, QtCore.QEvent.Type.MouseButtonPress, RMB, RMB)
        _send(w, QtCore.QEvent.Type.MouseButtonRelease, RMB, NO_BTN)
    with patch.object(w._mouse_dispatcher, "_find_target_widget", return_value=w):
        _send(w, QtCore.QEvent.Type.MouseButtonPress, RMB, RMB)
        _send(w, QtCore.QEvent.Type.MouseButtonRelease, RMB, NO_BTN)
    assert runs == [MouseButton.RIGHT]
