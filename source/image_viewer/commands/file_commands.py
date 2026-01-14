import os
import json
import sys
from typing import List

from PySide6 import QtCore, QtGui

from ...actions.bridge import Command, Kit
from ...os.copy import ClipboardFileTransfer
from ...os.paste import ClipboardFilePaster, PasteDecision



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


def show_in_explorer(ctx):
    path = _ctx_path(ctx)
    if not path:
        return
    info = QtCore.QFileInfo(str(path))
    if not info.exists():
        return
    if sys.platform.startswith("win"):
        QtCore.QProcess.startDetached(
            "explorer",
            ["/select,", QtCore.QDir.toNativeSeparators(info.absoluteFilePath())],
        )
    else:
        QtCore.QProcess.startDetached("xdg-open", [info.absolutePath()])


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


def delete_files(ctx, permanent: bool = False):
    paths = _ctx_paths(ctx)
    if not paths:
        return
    if permanent:
        for p in paths:
            if os.path.exists(p) and os.path.isfile(p):
                os.remove(p)
        return
    try:
        import send2trash

        for p in paths:
            if os.path.exists(p):
                send2trash.send2trash(p)
    except ImportError:
        for p in paths:
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
    from ...qt.dialog import FileConflictDialog

    parent = ctx.get_instance("ViewerWidget") or ctx.get_instance("JustifiedView")

    conflict_count = sum(1 for p in plans if getattr(p, "conflict", False))
    show_apply_all = conflict_count > 1
    confirmed_mode = None
    decisions = {}
    for plan in plans:
        if not getattr(plan, "conflict", False):
            decisions[plan.index] = PasteDecision(mode="overwrite")
            continue
        mode = overwrite_mode
        if mode == "ask":
            if confirmed_mode is None:
                op = "move" if getattr(plan, "action", "copy") == "cut" else "copy"
                res, apply_all = FileConflictDialog.ask(
                    "同名ファイルが存在します。",
                    src_path=str(getattr(plan, "src", "") or ""),
                    dst_path=str(getattr(plan, "dst_default", "") or ""),
                    src_name=str(getattr(getattr(plan, "src", None), "name", "") or ""),
                    op=op,
                    show_apply_all=show_apply_all,
                    parent=parent,
                )
                choice = FileConflictDialog.parse_choice(res)
                if choice is None or choice == "cancel":
                    if apply_all:
                        confirmed_mode = "skip"
                    decisions[plan.index] = PasteDecision(mode="skip")
                    continue
                chosen = "overwrite" if choice == "overwrite" else "rename"
                if apply_all:
                    confirmed_mode = chosen
                mode = chosen
            else:
                mode = confirmed_mode
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
            params=[
                Kit.Param(
                    name="permanent",
                    value=False,
                    description="Delete permanently (do not use recycle bin)",
                )
            ],
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