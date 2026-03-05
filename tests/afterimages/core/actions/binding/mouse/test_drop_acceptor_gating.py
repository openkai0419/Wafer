from PySide6 import QtCore, QtGui, QtWidgets

from afterimages.core.actions.binding.mixins import CommandBindingMixin
from afterimages.core.actions.binding.mouse.types import ClickType, MouseActionKey, MouseButton
from afterimages.core.actions.binding.mouse.store import MouseBindingStore
from afterimages.core.actions.command.core import CommandMeta, CommandRegistry, DropAcceptRegistry, register_command_defs
from afterimages.core.actions.command.payload import CommandPayload


class _W(QtWidgets.QWidget, CommandBindingMixin):
    pass


def _drag_enter_event(mime: QtCore.QMimeData) -> QtGui.QDragEnterEvent:
    return QtGui.QDragEnterEvent(
        QtCore.QPoint(10, 10),
        QtCore.Qt.DropAction.CopyAction,
        mime,
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )


def test_drag_enter_is_rejected_without_drop_acceptor(qtbot):
    reg = CommandRegistry.instance()
    prev_cmds = reg.get_all_commands()
    prev_acceptors = dict(getattr(DropAcceptRegistry.instance(), "_acceptors", {}) or {})
    reg._commands = {}
    DropAcceptRegistry.instance()._acceptors = {}
    register_command_defs(
        [
            CommandMeta(
                id="__test__.drop_no_acceptor",
                category="drop",
                target_widgets=["GridView"],
                drop_callbacks={"drop": lambda ctx: None},
            )
        ]
    )

    store = MouseBindingStore.instance()
    try:
        w = _W()
        qtbot.addWidget(w)
        w.init_command_binding("GridView", enable_drops=True)
        key = MouseActionKey(MouseButton.NONE, ClickType.DROP, (), ())
        store.set_all({key: {"GridView": CommandPayload("__test__.drop_no_acceptor")}})

        mime = QtCore.QMimeData()
        mime.setUrls([QtCore.QUrl.fromLocalFile(__file__)])
        ev = _drag_enter_event(mime)
        w._mouse_dispatcher._handle_drag_enter(ev)
        assert ev.isAccepted() is False
    finally:
        store.set_all({})
        reg._commands = prev_cmds
        DropAcceptRegistry.instance()._acceptors = prev_acceptors


def test_drag_enter_is_accepted_with_drop_acceptor(qtbot):
    def _accept_any(ctx) -> bool:
        return True

    reg = CommandRegistry.instance()
    prev_cmds = reg.get_all_commands()
    prev_acceptors = dict(getattr(DropAcceptRegistry.instance(), "_acceptors", {}) or {})
    reg._commands = {}
    DropAcceptRegistry.instance()._acceptors = {}
    register_command_defs(
        [
            CommandMeta(
                id="__test__.drop_with_acceptor",
                category="drop",
                target_widgets=["GridView"],
                drop_acceptor=_accept_any,
                drop_callbacks={"drop": lambda ctx: None},
            )
        ]
    )

    store = MouseBindingStore.instance()
    try:
        w = _W()
        qtbot.addWidget(w)
        w.init_command_binding("GridView", enable_drops=True)
        key = MouseActionKey(MouseButton.NONE, ClickType.DROP, (), ())
        store.set_all({key: {"GridView": CommandPayload("__test__.drop_with_acceptor")}})

        mime = QtCore.QMimeData()
        mime.setUrls([QtCore.QUrl.fromLocalFile(__file__)])
        ev = _drag_enter_event(mime)
        w._mouse_dispatcher._handle_drag_enter(ev)
        assert ev.isAccepted() is True
    finally:
        store.set_all({})
        reg._commands = prev_cmds
        DropAcceptRegistry.instance()._acceptors = prev_acceptors
