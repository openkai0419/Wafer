import os

from PySide6 import QtCore, QtGui, QtWidgets

from wafer.core.commands.command.context import CommandContext
from wafer.utils.paths import normalize_path
from wafer.builtins.commands import grid as grid_module
from wafer.builtins.commands.grid import GridDropTarget, GridViewDropCommands


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
    monkeypatch.setattr(GridViewDropCommands, "_resolve_drop_target", staticmethod(lambda ctx, view, items: GridDropTarget(os.path.dirname(__file__), "hover", 0)))
    monkeypatch.setattr(GridViewDropCommands, "_extract_items", staticmethod(lambda event: [object()]))
    monkeypatch.setattr(grid_module, "drop_files_with_ui", lambda items, dst, op, overwrite_mode="ask", parent=None, confirm_message=None: [])

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
    monkeypatch.setattr(GridViewDropCommands, "_resolve_drop_target", staticmethod(lambda ctx, view, items: None))

    GridViewDropCommands._save(ctx, op="ask", on_conflict="ask")
    assert ev.dropAction() == QtCore.Qt.DropAction.IgnoreAction


def test_resolve_grid_drop_target_uses_nearest_source(tmp_path):
    target_file = tmp_path / "nearest.txt"
    target_file.write_text("x", encoding="utf-8")

    class _Ctx:
        pos = QtCore.QPoint(10, 10)

    class _View:
        rects = [QtCore.QRect(0, 0, 100, 100)]

        def index_at_pos(self, pos):
            return None

        def nearest_index_at_pos(self, pos):
            return 0

    class _Items:
        def source_at(self, index):
            assert index == 0
            return str(target_file)

        def path_at(self, index):
            raise AssertionError("path_at must not be used for file operations")

    target = GridViewDropCommands._resolve_grid_drop_target(_Ctx(), _View(), _Items())
    assert target == GridDropTarget(str(tmp_path), "nearest", 0)


def test_drop_save_nearest_target_without_confirm_message(qtbot, monkeypatch, tmp_path):
    class View(QtWidgets.QWidget):
        def viewport(self):
            return self

    view = View()
    qtbot.addWidget(view)
    mime = QtCore.QMimeData()
    mime.setUrls([QtCore.QUrl.fromLocalFile(__file__)])
    ev = _drag_enter_event(mime)
    ctx = CommandContext.create(view, None, source="drop", event=ev)
    calls = []
    target_dir = normalize_path(str(tmp_path))
    monkeypatch.setattr(grid_module.GridViewCommands, "get_view", staticmethod(lambda ctx: view))
    monkeypatch.setattr(grid_module.GridViewCommands, "get_items", staticmethod(lambda ctx: object()))
    monkeypatch.setattr(GridViewDropCommands, "_resolve_drop_target", staticmethod(lambda ctx, view, items: GridDropTarget(target_dir, "nearest", 0)))
    monkeypatch.setattr(GridViewDropCommands, "_extract_items", staticmethod(lambda event: ["src"]))
    monkeypatch.setattr(grid_module, "drop_files_with_ui", lambda *args, **kwargs: calls.append((args, kwargs)) or [])

    GridViewDropCommands._save(ctx, op="copy", on_conflict="ask")

    assert calls[0][0][1] == target_dir
    assert calls[0][1]["confirm_message"] is None
    assert ev.dropAction() == QtCore.Qt.DropAction.IgnoreAction


def test_drop_save_single_folder_tree_target_passes_confirm_message(qtbot, monkeypatch, tmp_path):
    class View(QtWidgets.QWidget):
        def viewport(self):
            return self

    view = View()
    qtbot.addWidget(view)
    mime = QtCore.QMimeData()
    mime.setUrls([QtCore.QUrl.fromLocalFile(__file__)])
    ev = _drag_enter_event(mime)
    ctx = CommandContext.create(view, None, source="drop", event=ev)
    calls = []
    target_dir = normalize_path(str(tmp_path))
    monkeypatch.setattr(grid_module.GridViewCommands, "get_view", staticmethod(lambda ctx: view))
    monkeypatch.setattr(grid_module.GridViewCommands, "get_items", staticmethod(lambda ctx: object()))
    monkeypatch.setattr(GridViewDropCommands, "_resolve_grid_drop_target", staticmethod(lambda ctx, view, items: None))
    monkeypatch.setattr(GridViewDropCommands, "_folder_tree_selected_dirs", staticmethod(lambda ctx: [target_dir]))
    monkeypatch.setattr(GridViewDropCommands, "_extract_items", staticmethod(lambda event: ["src"]))
    monkeypatch.setattr(grid_module, "drop_files_with_ui", lambda *args, **kwargs: calls.append((args, kwargs)) or [])

    GridViewDropCommands._save(ctx, op="copy", on_conflict="ask")

    assert calls[0][0][1] == target_dir
    assert target_dir in calls[0][1]["confirm_message"]


def test_drop_save_multiple_folder_tree_targets_uses_dialog_choice(qtbot, monkeypatch, tmp_path):
    class View(QtWidgets.QWidget):
        def viewport(self):
            return self

    a = normalize_path(str(tmp_path / "a"))
    b = normalize_path(str(tmp_path / "b"))
    os.makedirs(a, exist_ok=True)
    os.makedirs(b, exist_ok=True)
    view = View()
    qtbot.addWidget(view)
    mime = QtCore.QMimeData()
    mime.setUrls([QtCore.QUrl.fromLocalFile(__file__)])
    ev = _drag_enter_event(mime)
    ctx = CommandContext.create(view, None, source="drop", event=ev)
    calls = []
    monkeypatch.setattr(grid_module.GridViewCommands, "get_view", staticmethod(lambda ctx: view))
    monkeypatch.setattr(grid_module.GridViewCommands, "get_items", staticmethod(lambda ctx: object()))
    monkeypatch.setattr(GridViewDropCommands, "_resolve_grid_drop_target", staticmethod(lambda ctx, view, items: None))
    monkeypatch.setattr(GridViewDropCommands, "_folder_tree_selected_dirs", staticmethod(lambda ctx: [a, b]))
    monkeypatch.setattr(GridViewDropCommands, "_folder_tree_current_dir", staticmethod(lambda ctx: b))
    monkeypatch.setattr(grid_module.DropTargetDialog, "ask", staticmethod(lambda candidates, default=None, message=None, title=None, parent=None: b))
    monkeypatch.setattr(GridViewDropCommands, "_extract_items", staticmethod(lambda event: ["src"]))
    monkeypatch.setattr(grid_module, "drop_files_with_ui", lambda *args, **kwargs: calls.append((args, kwargs)) or [])

    GridViewDropCommands._save(ctx, op="copy", on_conflict="ask")

    assert calls[0][0][1] == b
    assert calls[0][1]["confirm_message"] is None


def test_drop_save_empty_grid_without_folder_selection_shows_dialog(qtbot, monkeypatch):
    class View(QtWidgets.QWidget):
        def viewport(self):
            return self

    view = View()
    qtbot.addWidget(view)
    mime = QtCore.QMimeData()
    mime.setUrls([QtCore.QUrl.fromLocalFile(__file__)])
    ev = _drag_enter_event(mime)
    ctx = CommandContext.create(view, None, source="drop", event=ev)
    messages = []
    monkeypatch.setattr(grid_module.GridViewCommands, "get_view", staticmethod(lambda ctx: view))
    monkeypatch.setattr(grid_module.GridViewCommands, "get_items", staticmethod(lambda ctx: object()))
    monkeypatch.setattr(GridViewDropCommands, "_resolve_grid_drop_target", staticmethod(lambda ctx, view, items: None))
    monkeypatch.setattr(GridViewDropCommands, "_folder_tree_selected_dirs", staticmethod(lambda ctx: []))
    monkeypatch.setattr(grid_module.ConfirmDialog, "ask", staticmethod(lambda message, **kwargs: messages.append(message) or "OK"))
    monkeypatch.setattr(GridViewDropCommands, "_extract_items", staticmethod(lambda event: ["src"]))
    monkeypatch.setattr(grid_module, "drop_files_with_ui", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("drop must not execute")))

    GridViewDropCommands._save(ctx, op="copy", on_conflict="ask")

    assert messages
    assert ev.dropAction() == QtCore.Qt.DropAction.IgnoreAction


def test_drop_target_dir_from_hover_uses_source_only(monkeypatch, tmp_path):
    archive = tmp_path / "archive.zip"

    class _Items:
        def source_at(self, index):
            assert index == 0
            return str(archive)

        def path_at(self, index):
            raise AssertionError("path_at must not be used for file operations")

    monkeypatch.setattr(GridViewDropCommands, "_hover_index", staticmethod(lambda ctx, view: 0))

    dst = GridViewDropCommands._drop_target_dir_from_hover(object(), object(), _Items())
    assert dst == str(tmp_path)


def test_drop_target_dir_from_hover_returns_none_without_source(monkeypatch):
    class _Items:
        def source_at(self, index):
            assert index == 0
            return None

        def path_at(self, index):
            raise AssertionError("path_at must not be used for file operations")

    monkeypatch.setattr(GridViewDropCommands, "_hover_index", staticmethod(lambda ctx, view: 0))

    assert GridViewDropCommands._drop_target_dir_from_hover(object(), object(), _Items()) is None


def test_drop_target_dir_requires_source_and_does_not_use_view_root():
    class _Ctx:
        def get(self, key, default=None):
            return default

    class _Root:
        def __str__(self):
            raise AssertionError("view.root must not be used for file operations")

    class _View:
        root = _Root()

    assert GridViewDropCommands._drop_target_dir(_Ctx(), _View()) is None
