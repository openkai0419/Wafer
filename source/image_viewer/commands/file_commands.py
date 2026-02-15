import os
import json
import sys
from pathlib import Path
from typing import List

from PySide6 import QtCore, QtGui

from ...actions.bridge import Command, Kit
from ...qt.dialog import ConfirmDialog, ThumbnailConfirmDialog
from ...os.copy import ClipboardFileTransfer
from ...os.save import paste_clipboard_files, unique_path, get_os_new_folder_name
from ...os.folders import show_in_explorer as reveal_in_explorer
from ...common.profiling import logger



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
    if path is None:
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
    try:
        import send2trash
        for p in norm_paths:
            if os.path.exists(p):
                try:
                    send2trash.send2trash(p)
                except Exception:
                    if os.path.isfile(p):
                        os.remove(p)
    except ImportError:
        for p in norm_paths:
            if os.path.exists(p) and os.path.isfile(p):
                os.remove(p)


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

def select_path(ctx):
    get = getattr(ctx, "get", None)
    path = get("path") if callable(get) else None
    if not path:
        return
    folder = _get_directory_from_path(str(path))
    ftree = ctx.get_instance("FolderTree")
    ftree.expand_and_select_path(folder)


def _push_overlay(ctx, text: str, level: str = "info", duration: int = 3000):
    stack = ctx.get_instance("OverlayStack")
    if stack is not None:
        stack.push(text, level=level, duration=duration)


def scroll_to_file(ctx):
    path = _ctx_path(ctx)
    if not path:
        return
    items = ctx.get_instance("ViewerItems")
    if items is None:
        return
    idx = items.index_of_path(path)
    if idx is None:
        _push_overlay(ctx, f"File not found in view")
        return
    view = ctx.get_instance("GridView")
    if view is None or not hasattr(view, "rects"):
        return
    if idx >= len(view.rects):
        _push_overlay(ctx, f"File out of visible area")
        return
    view.reinstall_scroll_index(idx, animated=True)


def show_file(ctx):
    path = _ctx_path(ctx)
    if not path:
        return
    shower = ctx.get_instance("FileViewerWidget")
    if shower is None:
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


class FileCommands(Kit.MenuBase):
    prefix = "File"

    commands = [
        ":File",
        Kit.Command(path="file.open", display="Open File", func=open_file),
        Kit.Command(
            path="file.show_explorer",
            display="Reveal in Explorer",
            params=[
                Kit.Param(
                    name="show_first_if_folder",
                    value=False,
                    description="open if folder",
                )
            ],
            func=show_in_explorer,
        ),
        "-",
        Kit.Command(path="file.copy_path", display="Copy Path", func=copy_path),
        Kit.Command(
            path="file.copy_path_list",
            display="Copy Paths",
            func=copy_path_list,
        ),
        Kit.Command(path="file.copy_filename", display="Copy FileName", func=copy_filename),
        "-",
        Kit.Command(path="file.select_path", display="Select Folder", func=select_path),
        Kit.Command(path="file.scroll_to_file", display="Scroll To File", func=scroll_to_file),
        #Kit.Command(path="file.show_file", display="Show File", func=show_file),
        "-",
        Kit.Command(path="file.copy",  display="Copy", func=copy_files),
        Kit.Command(path="file.cut",  display="Cut", func=cut_files),
        Kit.Command(
            path="file.delete",
            display="Delete",
            func=delete_files,
        ),
        "-",
        Kit.Command(
            path="file.paste",
            display="Paste here",
            params=[
                Kit.Param(
                    name="overwrite_mode",
                    value=["ask", "skip", "overwrite", "rename"],
                    description="Overwrite mode",
                    default="ask",
                )
            ],
            func=paste_here,
        ),
                Kit.Command(
            path="file.new_folder",
            display="New Folder here",
            params=[
                Kit.Param(
                    name="folder_name",
                    value="",
                    description="Folder name (empty for default)",
                )
            ],
            func=make_new_folder_here,
        ),
    ]