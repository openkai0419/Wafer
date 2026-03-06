from PySide6 import QtCore, QtGui, QtWidgets

from wayfer.core.actions.binding.mixins import CommandBindingMixin
from wayfer.core.actions.binding.mouse.types import ClickType, MouseActionKey, MouseButton
from wayfer.core.actions.binding.mouse.store import MouseBindingStore
from wayfer.core.actions.command.core import CommandBase, CommandMeta, CommandRegistry
from wayfer.core.actions.command.payload import CommandPayload
from wayfer.core.actions.command.state import CommandOptionStore


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


def test_wheel_steps_are_normalized_and_passed_to_ctx(qtbot, tmp_path):
    prev_instance = getattr(CommandOptionStore, "_instance", None)
    prev_default_path = getattr(CommandOptionStore, "_default_path", None)
    CommandOptionStore._instance = None
    CommandOptionStore._default_path = None
    CommandOptionStore.configure(tmp_path / "command_options.json")

    reg = CommandRegistry.instance()
    if not reg.has_command("__test__.wheel_capture"):
        reg.register(_CaptureWheelSteps)

    store = MouseBindingStore.instance()
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
        CommandOptionStore._instance = prev_instance
        CommandOptionStore._default_path = prev_default_path
