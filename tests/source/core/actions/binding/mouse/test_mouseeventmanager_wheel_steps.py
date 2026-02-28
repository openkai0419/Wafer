from PySide6 import QtCore, QtGui, QtWidgets

from source.core.actions.binding.mixins import CommandBindingMixin
from source.core.actions.binding.mouse.mouseeventmanager import ClickType, MouseActionKey, MouseButton
from source.core.actions.binding.mouse.store import MouseBindingStore
from source.core.actions.command.core import CommandBase, CommandMeta, CommandRegistry
from source.core.actions.command.payload import CommandPayload


class _W(QtWidgets.QWidget, CommandBindingMixin):
    pass


class _CaptureWheelSteps(CommandBase):
    meta = CommandMeta(id="__test__.wheel_capture")
    captured = None

    def execute(self, **kwargs):
        ctx = kwargs.get("ctx")
        _CaptureWheelSteps.captured = ctx.get("wheel_steps")


def _wheel_event(*, angle_y: int) -> QtGui.QWheelEvent:
    return QtGui.QWheelEvent(
        QtCore.QPointF(10, 10),
        QtCore.QPointF(10, 10),
        QtCore.QPoint(0, 0),
        QtCore.QPoint(0, angle_y),
        QtCore.Qt.MouseButton.NoButton,
        QtCore.Qt.KeyboardModifier.NoModifier,
        QtCore.Qt.ScrollPhase.NoScrollPhase,
        False,
    )


def test_wheel_steps_are_normalized_and_passed_to_ctx(qtbot):
    reg = CommandRegistry()
    if not reg.has_command("__test__.wheel_capture"):
        reg.register(_CaptureWheelSteps)

    store = MouseBindingStore()
    try:
        w = _W()
        qtbot.addWidget(w)
        w.init_command_binding("ImageView")

        key_up = MouseActionKey(MouseButton.NONE, ClickType.WHEEL_UP, (), ())
        store.set_all({key_up: {"ImageView": CommandPayload("__test__.wheel_capture")}})

        _CaptureWheelSteps.captured = None
        ev = _wheel_event(angle_y=240)
        ok = w._mouse_dispatcher._handle_wheel(ev)
        assert ok is True
        assert _CaptureWheelSteps.captured == 2
    finally:
        store.set_all({})
