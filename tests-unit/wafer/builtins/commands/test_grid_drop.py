from PySide6 import QtCore, QtGui, QtWidgets

from wafer.core.commands.command.context import CommandContext
from wafer.builtins.commands import grid as grid_module
from wafer.builtins.commands.grid import GridViewDropCommands


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


def test_drop_enter_ask_uses_saved_operation(qtbot, monkeypatch):
    qtbot.addWidget(QtWidgets.QWidget())
    monkeypatch.setattr(grid_module, "get_saved_drop_operation", lambda: "move")
    mime = QtCore.QMimeData()
    mime.setUrls([QtCore.QUrl.fromLocalFile(__file__)])
    ev = _drag_enter_event(mime)
    ctx = CommandContext.create(None, None, source="drop", event=ev)
    GridViewDropCommands._apply_drop_action(ctx, "ask")
    assert ev.dropAction() == QtCore.Qt.DropAction.MoveAction


def test_drop_save_finalizes_ignore_action(qtbot, monkeypatch):
    class View(QtWidgets.QWidget):
        def viewport(self):
            return self

    view = View()
    qtbot.addWidget(view)
    view._drop_preview_rect = object()
    view._drop_preview_title = "Copy to:"
    view._drop_preview_text = "dst"

    mime = QtCore.QMimeData()
    mime.setUrls([QtCore.QUrl.fromLocalFile(__file__)])
    ev = _drag_enter_event(mime)
    ctx = CommandContext.create(view, None, source="drop", event=ev)
    monkeypatch.setattr(grid_module.GridViewCommands, "get_view", staticmethod(lambda ctx: view))
    monkeypatch.setattr(grid_module.GridViewCommands, "get_items", staticmethod(lambda ctx: object()))
    monkeypatch.setattr(GridViewDropCommands, "_drop_target_dir_from_hover", staticmethod(lambda ctx, view, items: __file__))
    monkeypatch.setattr(GridViewDropCommands, "_extract_items", staticmethod(lambda event: [object()]))
    monkeypatch.setattr(grid_module, "drop_files_with_ui", lambda items, dst, op, overwrite_mode="ask", parent=None: [])

    GridViewDropCommands._save(ctx, op="ask", on_conflict="ask")
    assert ev.dropAction() == QtCore.Qt.DropAction.IgnoreAction


def test_drop_save_finalizes_ignore_action_without_target(qtbot, monkeypatch):
    class View(QtWidgets.QWidget):
        def viewport(self):
            return self

    view = View()
    qtbot.addWidget(view)
    mime = QtCore.QMimeData()
    mime.setUrls([QtCore.QUrl.fromLocalFile(__file__)])
    ev = _drag_enter_event(mime)
    ctx = CommandContext.create(view, None, source="drop", event=ev)
    monkeypatch.setattr(grid_module.GridViewCommands, "get_view", staticmethod(lambda ctx: view))
    monkeypatch.setattr(grid_module.GridViewCommands, "get_items", staticmethod(lambda ctx: object()))
    monkeypatch.setattr(GridViewDropCommands, "_drop_target_dir_from_hover", staticmethod(lambda ctx, view, items: None))

    GridViewDropCommands._save(ctx, op="ask", on_conflict="ask")
    assert ev.dropAction() == QtCore.Qt.DropAction.IgnoreAction
