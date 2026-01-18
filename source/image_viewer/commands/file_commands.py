import os
import json
import sys
from typing import List

from PySide6 import QtCore, QtGui

from ...actions.bridge import Command, Kit
from ...qt.dialog import ConfirmDialog
from ...os.copy import ClipboardFileTransfer
from ...os.paste import ClipboardFilePaster, PasteDecision
from ...os.folders import show_in_explorer as reveal_in_explorer



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


def _confirm_delete(ctx, paths) -> bool:
    parent = ctx.get("widget") if hasattr(ctx, "get") else None
    if parent is None and hasattr(ctx, "get_instance"):
        parent = ctx.get_instance("ViewerWidget") or ctx.get_instance("JustifiedView") or ctx.get_instance("FolderTree")
    title = "Delete"
    head = "Move to recycle bin?"
    shown = "\n".join(paths[:5])
    more = f"\n+{len(paths) - 5} more" if len(paths) > 5 else ""
    msg = f"{head}\n{len(paths)} item(s)\n{shown}{more}"
    return ConfirmDialog.ask(msg, title=title, buttons=("Delete", "Cancel"), parent=parent) == "Delete"


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
    paster = ClipboardFilePaster()
    plans = paster.build_paste_plan(d)
    from ...qt.file_conflict_resolver import make_session
    from ...os.file_transfer_utils import check_copy_conflict

    parent = ctx.get_instance("ViewerWidget") or ctx.get_instance("JustifiedView")

    conflict_count = sum(1 for p in plans if getattr(p, "conflict", False))
    session = make_session(op=("move" if (plans and getattr(plans[0], "action", "copy") == "cut") else "copy"), parent=parent, item_count=conflict_count)
    decisions = {}
    for plan in plans:
        if not getattr(plan, "conflict", False):
            decisions[plan.index] = PasteDecision(mode="overwrite")
            continue
        srcp = getattr(plan, "src", None)
        dstp = getattr(plan, "dst_default", None)
        if srcp is not None and dstp is not None:
            c = check_copy_conflict(srcp, dstp)
            if c in ("same_path", "subpath"):
                if session.resolve_copy_conflict(src_path=str(srcp), dst_path=str(dstp), name=str(getattr(srcp, "name", "") or "")):
                    decisions[plan.index] = PasteDecision(mode="skip")
                    continue
        mode = overwrite_mode
        if mode == "ask":
            mode = session.resolve_exists(
                src_path=str(getattr(plan, "src", "") or ""),
                dst_path=str(getattr(plan, "dst_default", "") or ""),
                name=str(getattr(getattr(plan, "src", None), "name", "") or ""),
                src_bytes=None,
                default_mode="ask",
            )
        decisions[plan.index] = PasteDecision(mode=mode if mode in ("overwrite", "rename", "skip") else "skip")
    paster.execute_paste(plans, decisions)

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
            display="Copy Path List",
            func=copy_path_list,
        ),
        Kit.Command(path="file.copy_filename", display="Copy FileName", func=copy_filename),
        "-",
        Kit.Command(path="file.select_path", display="Select Folder", func=select_path),
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
    ]