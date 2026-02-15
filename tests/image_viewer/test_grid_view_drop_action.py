from PySide6 import QtCore, QtGui, QtWidgets

from source.actions.command.context import CommandContext
from source.image_viewer.commands.grid_view import GridViewDropCommands


def _drag_enter_event(mime: QtCore.QMimeData) -> QtGui.QDragEnterEvent:
    return QtGui.QDragEnterEvent(
        QtCore.QPoint(10, 10),
        QtCore.Qt.DropAction.CopyAction | QtCore.Qt.DropAction.MoveAction,
        mime,
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )


def test_drop_enter_sets_copy_action(qtbot):
    qtbot.addWidget(QtWidgets.QWidget())
    mime = QtCore.QMimeData()
    mime.setUrls([QtCore.QUrl.fromLocalFile(__file__)])
    ev = _drag_enter_event(mime)
    ctx = CommandContext.create(None, None, source="drop", event=ev)
    GridViewDropCommands._apply_drop_action(ctx, "copy")
    assert ev.dropAction() == QtCore.Qt.DropAction.CopyAction


def test_drop_enter_sets_move_action(qtbot):
    qtbot.addWidget(QtWidgets.QWidget())
    mime = QtCore.QMimeData()
    mime.setUrls([QtCore.QUrl.fromLocalFile(__file__)])
    ev = _drag_enter_event(mime)
    ctx = CommandContext.create(None, None, source="drop", event=ev)
    GridViewDropCommands._apply_drop_action(ctx, "move")
    assert ev.dropAction() == QtCore.Qt.DropAction.MoveAction


def test_drop_enter_sets_ignore_action(qtbot):
    qtbot.addWidget(QtWidgets.QWidget())
    mime = QtCore.QMimeData()
    mime.setUrls([QtCore.QUrl.fromLocalFile(__file__)])
    ev = _drag_enter_event(mime)
    ctx = CommandContext.create(None, None, source="drop", event=ev)
    GridViewDropCommands._apply_drop_action(ctx, "ignore")
    assert ev.dropAction() == QtCore.Qt.DropAction.IgnoreAction
