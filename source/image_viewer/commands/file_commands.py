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
    decisions = {
        plan.index: PasteDecision(mode=overwrite_mode if plan.conflict else "overwrite")
        for plan in plans
    }
    paster.execute_paste(plans, decisions)


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
        "-",
        Kit.Command(path="file.copy",  display="Copy", func=copy_files),
        Kit.Command(path="file.cut",  display="Cut", func=cut_files),
        Kit.Command(
            path="file.delete",
            display="Delete",
            has_options=True,
            params=[
                Kit.Param(
                    name="permanent",
                    value=False,
                    description="Delete permanently (bypass recycle bin)",
                )
            ],
            func=delete_files,
        ),
        "-",
        Kit.Command(
            path="file.paste",
            display="Paste here",
            has_options=True,
            params=[
                Kit.Param(
                    name="overwrite_mode",
                    value=["skip", "overwrite", "rename"],
                    description="Overwrite mode",
                    default="skip",
                )
            ],
            func=paste_here,
        ),
    ]