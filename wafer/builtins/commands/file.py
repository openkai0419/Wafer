import os
import json
import sys
from pathlib import Path

from PySide6 import QtCore, QtGui

from ...core.commands.bridge import ActionKit
from ...core.commands.command.require import require
from ...ui.dialogs import ThumbnailConfirmDialog
from ...core.platform.copy import ClipboardFileTransfer
from ...core.platform.paste import paste_clipboard_files, execute_paste_plans_with_ui
from ...core.platform.path_utils import unique_path, get_os_new_folder_name, validate_filename
from ...core.platform.file_operations import PastePlanItem, delete_to_trash
from ...core.platform.folders import show_in_explorer as reveal_in_explorer, open_file as platform_open_file, make_directory
from ...utils.logs import AppLogger
from ...utils.notifier import Notifier
from ...core.qt.dispatcher import Dispatcher
from ...core.qt.thread import SimpleThreadPool

_file_cmd_pool = SimpleThreadPool("file_cmd")
_file_cmd_dispatcher = Dispatcher(_file_cmd_pool)


def _ctx_paths(ctx) -> list[str]:
    paths = ctx.get("paths")
    if isinstance(paths, list) and paths:
        return [str(p) for p in paths if p]
    p = ctx.get("path")
    return [str(p)] if p else []


def _ctx_path(ctx) -> str | None:
    p = ctx.get("path")
    if p:
        return str(p)
    ps = _ctx_paths(ctx)
    return ps[0] if ps else None


def _ctx_sources(ctx) -> list[str]:
    sources = ctx.get("sources")
    if isinstance(sources, list) and sources:
        return list(dict.fromkeys(str(p) for p in sources if p))
    source = ctx.get("source")
    if source:
        return [str(source)]
    AppLogger.warning("[file_cmd] context did not provide 'source'/'sources'; file operation skipped. UI must populate source via extend_context().")
    return []


def _ctx_source(ctx) -> str | None:
    source = ctx.get("source")
    if source:
        return str(source)
    AppLogger.warning("[file_cmd] context did not provide 'source'; file operation skipped. UI must populate source via extend_context().")
    return None


def open_file(ctx):
    path = _ctx_source(ctx)
    if not path:
        return
    platform_open_file(path)


def show_in_explorer(ctx, show_first_if_folder: bool = False):
    path = _ctx_source(ctx)
    if not path:
        return
    reveal_in_explorer(str(path), show_first_if_folder=bool(show_first_if_folder))


def copy_path(ctx):
    paths = _ctx_sources(ctx)
    if not paths:
        return
    if len(paths) == 1:
        QtGui.QGuiApplication.clipboard().setText(paths[0])
    else:
        QtGui.QGuiApplication.clipboard().setText(json.dumps(paths, ensure_ascii=False))


def copy_filename(ctx):
    paths = _ctx_sources(ctx)
    if not paths:
        return
    if len(paths) == 1:
        QtGui.QGuiApplication.clipboard().setText(os.path.basename(paths[0]))
    else:
        names = [os.path.basename(p) for p in paths]
        QtGui.QGuiApplication.clipboard().setText(json.dumps(names, ensure_ascii=False))


def copy_files(ctx):
    paths = _ctx_sources(ctx)
    if not paths:
        return
    ClipboardFileTransfer().set_files(paths, cut=False)


def cut_files(ctx):
    paths = _ctx_sources(ctx)
    if not paths:
        return
    ClipboardFileTransfer().set_files(paths, cut=True)


def _count_files_in_path(path: str) -> int:
    if os.path.isfile(path):
        return 1
    if not os.path.isdir(path):
        return 0
    count = 0
    for _, _, files in os.walk(path):
        count += len(files)
    return count


def _confirm_delete(ctx, paths) -> bool:
    parent = ctx.get("widget") if hasattr(ctx, "get") else None
    if parent is None and hasattr(ctx, "get_instance"):
        parent = ctx.get_instance("ContentViewerWidget") or ctx.get_instance("GridView") or ctx.get_instance("FolderTree")
    title = "Delete"
    head = "Are you sure to delete"

    dir_count = sum(1 for p in paths if os.path.isdir(p))
    file_count = sum(1 for p in paths if os.path.isfile(p))

    shown = "\n".join(paths[:5])
    more = f"\n+{len(paths) - 5} more" if len(paths) > 5 else ""
    i = "item" if len(paths) == 1 else "items"
    if dir_count > 0:
        msg = f"{head} {len(paths)} {i} (counting...) ?\n{shown}{more}"
    else:
        msg = f"{head} {len(paths)} {i} ?\n{shown}{more}"
    thumbs = [p for p in paths if p][:4]
    dialog = ThumbnailConfirmDialog(msg, paths=thumbs, title=title, buttons=("Delete", "Cancel"), parent=parent)

    if dir_count > 0:

        def count_task():
            total = file_count
            for p in paths:
                if os.path.isdir(p):
                    total += _count_files_in_path(p)
            updated = f"{head} {len(paths)} {i} ({total} files) ?\n{shown}{more}"
            _file_cmd_dispatcher.invoke(lambda: _update_if_open(updated))

        def _update_if_open(text):
            if dialog.result_text is None:
                dialog.message_label.setText(text)

        _file_cmd_dispatcher.post(count_task)

    dialog.exec()
    return dialog.result_text == "Delete"


def delete_files(ctx):
    paths = _ctx_sources(ctx)
    if not paths:
        return
    if not _confirm_delete(ctx, paths):
        return
    results = delete_to_trash(paths)
    for r in results:
        if r.status == "error":
            AppLogger.warning(f"Delete failed: {r.src} ({r.error})")
            Notifier.warning(f"Delete failed: {os.path.basename(r.src)}")


def paste_here(ctx, overwrite_mode: str = "skip"):
    path = _ctx_source(ctx)
    if not path:
        return
    a = os.path.abspath(path)
    d = a if os.path.isdir(a) else os.path.dirname(a)
    parent = ctx.get_instance("ContentViewerWidget") or ctx.get_instance("GridView") or ctx.get_instance("FolderTree")
    paste_clipboard_files(d, overwrite_mode=overwrite_mode, parent=parent)


def _get_directory_from_path(path):
    abs_path = os.path.abspath(path)
    return abs_path if os.path.isdir(abs_path) else os.path.dirname(abs_path)


@require(ftree="FolderTree")
def select_path(ctx, ftree):
    paths = _ctx_sources(ctx)
    if not paths:
        return
    folders = list(dict.fromkeys(_get_directory_from_path(str(p)) for p in paths))
    ftree.expand_and_select_paths(folders)


@require(items="GridItemModel", view="GridView")
def scroll_to_file(ctx, items, view):
    path = _ctx_path(ctx)
    if not path:
        return
    idx = items.index_of_path(path)
    if idx is None:
        Notifier.info("File not found in view")
        return
    if idx >= len(view.rects):
        Notifier.info("File out of visible area")
        return
    view.scroll_to_index(idx, animated=True)


@require(provider="FileListProvider")
def show_file(ctx, provider):
    path = _ctx_path(ctx)
    if not path:
        return
    provider.on_file_set(path)


def make_new_folder_here(ctx, folder_name: str | None = None) -> str | None:
    path = _ctx_source(ctx)
    if not path:
        return None
    parent_dir = _get_directory_from_path(path)
    name = folder_name or get_os_new_folder_name()
    new_folder = unique_path(parent_dir, name)
    make_directory(new_folder)
    return new_folder


def rename_file(ctx):
    path = _ctx_source(ctx)
    if not path or not os.path.isfile(path):
        return
    from ...ui.dialogs import InputDialog

    parent = ctx.get_instance("ContentViewerWidget") or ctx.get_instance("GridView")
    old_name = os.path.basename(path)
    new_name = InputDialog.get_text(
        f"Rename: {old_name}",
        title="Rename",
        parent=parent,
        default=old_name,
    )
    if not new_name or new_name == old_name:
        return
    issues = validate_filename(new_name)
    if issues:
        Notifier.warning(f"Invalid filename: {', '.join(issues)}")
        return
    src = Path(path)
    dst = src.parent / new_name
    conflict = dst.exists() and not _is_same_file(src, dst)
    plan = [
        PastePlanItem(
            index=0,
            src=src,
            is_dir=False,
            action="cut",
            dst_default=dst,
            conflict=conflict,
            suggested_dst=Path(unique_path(dst.parent, new_name)) if conflict else None,
        )
    ]
    results = execute_paste_plans_with_ui(plans=plan, overwrite_mode="ask", parent=parent)
    if not results or results[0].status == "skipped":
        return
    if results[0].status == "ok":
        final = Path(results[0].dst).name if results[0].dst else new_name
        Notifier.info(f"Renamed: {old_name} \u2192 {final}")
    else:
        AppLogger.warning(f"Rename failed: {path} ({results[0].error})")
        Notifier.warning(f"Rename failed: {results[0].error}")


def _is_same_file(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return False


def _batch_rename_widget(w):
    from wafer.builtins.batch_renamer import BatchRenameWidget

    panel = w._layout_manager.panel_widget("Batch Renamer")
    if isinstance(panel, BatchRenameWidget):
        return panel
    return None


@require(w="MainWindow")
def batch_rename(ctx, w):
    source_paths = _ctx_sources(ctx)
    if not source_paths:
        Notifier.info("No files selected")
        return
    file_paths = [Path(p) for p in source_paths]
    widget = _batch_rename_widget(w)
    if widget is None:
        return
    widget.set_files(file_paths, keys=source_paths, db_path=w.database_path)
    w._layout_manager.ensure_panel_visible("Batch Renamer")


@require(w="MainWindow")
def batch_rename_add(ctx, w):
    source_paths = _ctx_sources(ctx)
    if not source_paths:
        Notifier.info("No files selected")
        return
    file_paths = [Path(p) for p in source_paths]
    widget = _batch_rename_widget(w)
    if widget is None:
        return
    if widget._db_path != w.database_path:
        widget.set_files(file_paths, keys=source_paths, db_path=w.database_path)
    else:
        widget.add_files(file_paths, keys=source_paths)
    w._layout_manager.ensure_panel_visible("Batch Renamer")


@require(w="MainWindow")
def batch_rename_remove(ctx, w):
    source_paths = _ctx_sources(ctx)
    if not source_paths:
        Notifier.info("No files selected")
        return
    file_paths = [Path(p) for p in source_paths]
    widget = _batch_rename_widget(w)
    if widget is None:
        return
    widget.remove_files(file_paths)


def shell_context_menu(ctx):
    if not sys.platform.startswith("win"):
        return
    paths = _ctx_sources(ctx)
    if not paths:
        return
    from ...core.platform.shell_menu import show_shell_context_menu

    widget = ctx.get("widget")
    if widget is None:
        widget = QtGui.QGuiApplication.focusWindow()
    hwnd = int(widget.winId()) if widget and hasattr(widget, "winId") else 0
    if not hwnd:
        app_win = QtCore.QCoreApplication.instance()
        if app_win:
            for w in app_win.topLevelWidgets() if hasattr(app_win, "topLevelWidgets") else []:
                if w.isVisible():
                    hwnd = int(w.winId())
                    break
    if not hwnd:
        return
    gp = ctx.get("global_pos")
    if gp and hasattr(gp, "x"):
        x, y = gp.x(), gp.y()
    else:
        cursor_pos = QtGui.QCursor.pos()
        x, y = cursor_pos.x(), cursor_pos.y()
    show_shell_context_menu(paths, hwnd, x, y)


class FileCommands(ActionKit.MenuBase):
    NAME = "File"
    SCOPE = "*"
    PRIORITY = 10

    @classmethod
    def commands(cls):
        return [
            ":File",
            ActionKit.Command(path="file.open", display="Open File", func=open_file),
            ActionKit.Command(
                path="file.show_explorer",
                display="Reveal in Explorer",
                params=[
                    ActionKit.Param(
                        name="show_first_if_folder",
                        value=False,
                        description="open if folder",
                    )
                ],
                func=show_in_explorer,
            ),
            ActionKit.Command(path="file.shell_context_menu", display="Shell Context Menu", func=shell_context_menu),
            "-",
            ActionKit.Command(path="file.copy_path", display="Copy Paths(s)", func=copy_path),
            ActionKit.Command(path="file.copy_filename", display="Copy FileName(s)", func=copy_filename),
            "-",
            ActionKit.Command(path="file.copy", display="Copy", func=copy_files),
            ActionKit.Command(path="file.cut", display="Cut", func=cut_files),
            ActionKit.Command(path="file.rename", display="Rename", func=rename_file),
            ActionKit.Command(
                path="file.delete",
                display="Delete",
                func=delete_files,
            ),
            "-",
            ActionKit.Command(
                path="file.paste",
                display="Paste here",
                params=[
                    ActionKit.Param(
                        name="overwrite_mode",
                        value=["ask", "skip", "overwrite", "rename"],
                        description="Overwrite mode",
                        default="ask",
                    )
                ],
                func=paste_here,
            ),
            ActionKit.Command(
                path="file.new_folder",
                display="New Folder here",
                params=[
                    ActionKit.Param(
                        name="folder_name",
                        value="",
                        description="Folder name (empty for default)",
                    )
                ],
                func=make_new_folder_here,
            ),
        ]


class FileNavigationCommands(ActionKit.MenuBase):
    NAME = "File"
    PRIORITY = 10

    @classmethod
    def commands(cls):
        return [
            ":Wafer",
            ActionKit.Command(path="file.select_path", display="Select FolderTree", func=select_path),
            ActionKit.Command(path="file.scroll_to_file", display="Scroll to GridView", func=scroll_to_file),
            ActionKit.Command(path="file.show_file", display="Show at ContentViewer", func=show_file),
            "-",
            "Batch Renamer/:Batch Renamer",
            ActionKit.Command(path="Batch Renamer/file.batch_rename_add", display="Add", func=batch_rename_add),
            ActionKit.Command(path="Batch Renamer/file.batch_rename", display="Set", func=batch_rename),
            ActionKit.Command(path="Batch Renamer/file.batch_rename_remove", display="Remove", func=batch_rename_remove),
        ]
