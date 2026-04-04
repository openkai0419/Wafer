import os
import json
import sys
from pathlib import Path
from typing import List

from PySide6 import QtCore, QtGui

from ...core.commands.bridge import Command, ActionKit
from ...core.commands.command.require import require
from ...core.qt.dialog import ConfirmDialog, ThumbnailConfirmDialog
from ...core.platform.copy import ClipboardFileTransfer
from ...core.platform.paste import paste_clipboard_files, execute_paste_plans_with_ui
from ...core.platform.path_utils import unique_path, get_os_new_folder_name, validate_filename
from ...core.platform.file_operations import PastePlanItem
from ...core.platform.folders import show_in_explorer as reveal_in_explorer
from ...utils.logs import AppLogger
from ...utils.notifier import Notifier


def _ctx_paths(ctx) -> List[str]:
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


def open_file(ctx):
    path = _ctx_path(ctx)
    if not path:
        return
    QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))


def show_in_explorer(ctx, show_first_if_folder: bool = False):
    path = _ctx_path(ctx)
    if not path:
        return
    reveal_in_explorer(str(path), show_first_if_folder=bool(show_first_if_folder))


def copy_path(ctx):
    path = _ctx_path(ctx)
    if not path:
        return
    QtGui.QGuiApplication.clipboard().setText(str(path))


def copy_filename(ctx):
    path = _ctx_path(ctx)
    if not path:
        return
    QtGui.QGuiApplication.clipboard().setText(str(os.path.basename(path)))


def copy_path_list(ctx):
    paths = _ctx_paths(ctx)
    if not paths:
        return
    QtGui.QGuiApplication.clipboard().setText(json.dumps(paths, ensure_ascii=False))


def copy_files(ctx):
    paths = _ctx_paths(ctx)
    if not paths:
        return
    ClipboardFileTransfer().set_files(paths, cut=False)


def cut_files(ctx):
    paths = _ctx_paths(ctx)
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
        parent = ctx.get_instance("FileViewerWidget") or ctx.get_instance("GridView") or ctx.get_instance("FolderTree")
    title = "Delete"
    head = "Are you sure to delete"

    total_files = 0
    dir_count = 0
    for p in paths:
        if os.path.isdir(p):
            dir_count += 1
            total_files += _count_files_in_path(p)
        elif os.path.isfile(p):
            total_files += 1

    shown = "\n".join(paths[:5])
    more = f"\n+{len(paths) - 5} more" if len(paths) > 5 else ""
    if len(paths) == 1:
        i = "item"
    else:
        i = "items"
    if dir_count > 0:
        msg = f"{head} {len(paths)} {i} ({total_files} files) ?\n{shown}{more}"
    else:
        msg = f"{head} {len(paths)} {i} ?\n{shown}{more}"
    thumbs = [p for p in paths if p][:4]
    return ThumbnailConfirmDialog.ask(msg, title=title, buttons=("Delete", "Cancel"), parent=parent, paths=thumbs) == "Delete"


def delete_files(ctx):
    paths = _ctx_paths(ctx)
    if not paths:
        return
    if not _confirm_delete(ctx, paths):
        return
    norm_paths = [os.path.normpath(os.path.abspath(p)) for p in paths if p]
    AppLogger.info(f'Deleting {len(norm_paths)} files')
    try:
        import send2trash
        for p in norm_paths:
            if os.path.exists(p):
                try:
                    send2trash.send2trash(p)
                except Exception as e:
                    AppLogger.warning(f'send2trash failed: {p}', exc=e)
                    if os.path.isfile(p):
                        os.remove(p)
                    else:
                        Notifier.warning(f'Failed to delete folder (send2trash unavailable): {os.path.basename(p)}')
    except ImportError:
        for p in norm_paths:
            if os.path.exists(p):
                if os.path.isfile(p):
                    os.remove(p)
                else:
                    Notifier.warning(f'Cannot delete folder without send2trash: {os.path.basename(p)}')


def paste_here(ctx, overwrite_mode: str = "skip"):
    path = _ctx_path(ctx)
    if not path:
        return
    a = os.path.abspath(path)
    d = a if os.path.isdir(a) else os.path.dirname(a)
    parent = ctx.get_instance("FileViewerWidget") or ctx.get_instance("GridView") or ctx.get_instance("FolderTree")
    paste_clipboard_files(d, overwrite_mode=overwrite_mode, parent=parent)

def _get_directory_from_path(path):
    abs_path = os.path.abspath(path)
    return abs_path if os.path.isdir(abs_path) else os.path.dirname(abs_path)

@require(ftree="FolderTree")
def select_path(ctx, ftree):
    path = _ctx_path(ctx)
    if not path:
        return
    folder = _get_directory_from_path(str(path))
    ftree.expand_and_select_path(folder)


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


@require(shower="FileViewerWidget")
def show_file(ctx, shower):
    path = _ctx_path(ctx)
    if not path:
        return
    shower.set_path(path)


def make_new_folder_here(ctx, folder_name: str | None = None) -> str | None:
    path = _ctx_path(ctx)
    if not path:
        return None
    parent_dir = _get_directory_from_path(path)
    name = folder_name or get_os_new_folder_name()
    new_folder = unique_path(parent_dir, name)
    os.makedirs(new_folder, exist_ok=True)
    return new_folder


def rename_file(ctx):
    path = _ctx_path(ctx)
    if not path or not os.path.isfile(path):
        return
    from ...core.qt.dialog import InputDialog
    parent = ctx.get_instance("FileViewerWidget") or ctx.get_instance("GridView")
    old_name = os.path.basename(path)
    new_name = InputDialog.get_text(
        f'Rename: {old_name}',
        title='Rename',
        parent=parent,
        default=old_name,
    )
    if not new_name or new_name == old_name:
        return
    issues = validate_filename(new_name)
    if issues:
        Notifier.warning(f'Invalid filename: {", ".join(issues)}')
        return
    src = Path(path)
    dst = src.parent / new_name
    conflict = dst.exists() and not _is_same_file(src, dst)
    plan = [PastePlanItem(
        index=0, src=src, is_dir=False, action="cut",
        dst_default=dst, conflict=conflict,
        suggested_dst=Path(unique_path(dst.parent, new_name)) if conflict else None,
    )]
    results = execute_paste_plans_with_ui(plans=plan, overwrite_mode="ask", parent=parent)
    if not results or results[0].status == "skipped":
        return
    if results[0].status == "ok":
        final = Path(results[0].dst).name if results[0].dst else new_name
        Notifier.info(f'Renamed: {old_name} \u2192 {final}')
    else:
        AppLogger.warning(f'Rename failed: {path} ({results[0].error})')
        Notifier.warning(f'Rename failed: {results[0].error}')


def _is_same_file(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return False


@require(items="GridItemModel", w="MainWindow")
def batch_rename(ctx, items, w):
    paths_str = items.selected_paths()
    if not paths_str:
        Notifier.info('No files selected')
        return
    file_paths = [Path(p) for p in paths_str]
    from wafer.app.viewer.renamer import BatchRenameDialog
    BatchRenameDialog.open(file_paths, keys=paths_str, db_path=w.database_path, parent=w)


def shell_context_menu(ctx):
    if not sys.platform.startswith("win"):
        return
    paths = _ctx_paths(ctx)
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
            for w in app_win.topLevelWidgets() if hasattr(app_win, 'topLevelWidgets') else []:
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
            "-",
            ActionKit.Command(path="file.copy_path", display="Copy Path", func=copy_path),
            ActionKit.Command(
                path="file.copy_path_list",
                display="Copy Paths",
                func=copy_path_list,
            ),
            ActionKit.Command(path="file.copy_filename", display="Copy FileName", func=copy_filename),
            "-",
            ActionKit.Command(path="file.select_path", display="Select Folder", func=select_path),
            ActionKit.Command(path="file.scroll_to_file", display="Scroll To File", func=scroll_to_file),
            "-",
            ActionKit.Command(path="file.copy", display="Copy", func=copy_files),
            ActionKit.Command(path="file.cut", display="Cut", func=cut_files),
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
            "-",
            ActionKit.Command(path="file.rename", display="Rename", func=rename_file),
            ActionKit.Command(path="file.batch_rename", display="Batch Rename", func=batch_rename),
            "-",
            ActionKit.Command(path="file.shell_context_menu", display="Shell Context Menu", func=shell_context_menu),
        ]
