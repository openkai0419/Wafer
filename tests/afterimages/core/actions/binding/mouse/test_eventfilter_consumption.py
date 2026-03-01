from PySide6 import QtCore, QtGui, QtWidgets

from afterimages.core.actions.binding.mixins import CommandBindingMixin


class _W(QtWidgets.QWidget, CommandBindingMixin):
    pass


def _mouse_press_event() -> QtGui.QMouseEvent:
    return QtGui.QMouseEvent(
        QtCore.QEvent.Type.MouseButtonPress,
        QtCore.QPointF(10, 10),
        QtCore.QPointF(10, 10),
        QtCore.QPointF(10, 10),
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )


def test_eventfilter_uses_existing_events_when_enabled(qtbot):
    w = _W()
    qtbot.addWidget(w)
    w.init_command_binding("Viewer", use_existing_events=True)
    ev = _mouse_press_event()
    assert w._mouse_dispatcher.eventFilter(w, ev) is False


def test_eventfilter_overrides_events_when_disabled(qtbot):
    w = _W()
    qtbot.addWidget(w)
    w.init_command_binding("Viewer", use_existing_events=False)
    ev = _mouse_press_event()
    assert w._mouse_dispatcher.eventFilter(w, ev) is True
