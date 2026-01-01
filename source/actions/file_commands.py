import os
import json
import sys
from typing import List, Dict, Any
from PySide6 import QtCore, QtGui, QtWidgets
from .command.context import CommandContext
from .command.core import CommandMeta, CommandParam, register_command_defs
from ..os.copy import ClipboardFileTransfer
from ..os.paste import ClipboardFilePaster, PasteDecision
from ..common.profiling import logger, profiler

def _ctx_paths(ctx: CommandContext) -> List[str]:
    if ctx is None:
        return []
    paths = ctx.get("paths")
    if isinstance(paths, list) and paths:
        return [str(p) for p in paths if p]
    p = ctx.get("path")
    return [str(p)] if p else []


def _ctx_path(ctx: CommandContext) -> str | None:
    if ctx is None:
        return None
    p = ctx.get("path")
    if p:
        return str(p)
    ps = _ctx_paths(ctx)
    return ps[0] if ps else None


def open_file(ctx: CommandContext):
    path = _ctx_path(ctx)
    if not path:
        return
    QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))

def show_in_explorer(ctx: CommandContext):
    path = _ctx_path(ctx)
    if not path:
        return
    info = QtCore.QFileInfo(str(path))
    if not info.exists():
        return
    if sys.platform.startswith('win'):
        QtCore.QProcess.startDetached('explorer', ['/select,', QtCore.QDir.toNativeSeparators(info.absoluteFilePath())])
    else:
        QtCore.QProcess.startDetached('xdg-open', [info.absolutePath()])

def copy_path(ctx: CommandContext):
    path = _ctx_path(ctx)
    if path is None:
        return
    QtGui.QGuiApplication.clipboard().setText(str(path))

def copy_path_list(ctx: CommandContext):
    paths = _ctx_paths(ctx)
    if not paths:
        return
    QtGui.QGuiApplication.clipboard().setText(json.dumps(paths, ensure_ascii=False))

def copy_files(ctx: CommandContext):
    paths = _ctx_paths(ctx)
    if not paths:
        return
    ClipboardFileTransfer().set_files(paths, cut=False)

def cut_files(ctx: CommandContext):
    paths = _ctx_paths(ctx)
    if not paths:
        return
    ClipboardFileTransfer().set_files(paths, cut=True)

def delete_files(ctx: CommandContext, permanent: bool = False):
    paths = _ctx_paths(ctx)
    if not paths:
        return
    if permanent:
        for p in paths:
            if os.path.exists(p) and os.path.isfile(p):
                os.remove(p)
    else:
        try:
            import send2trash
            for p in paths:
                if os.path.exists(p):
                    send2trash.send2trash(p)
        except ImportError:
            for p in paths:
                if os.path.exists(p) and os.path.isfile(p):
                    os.remove(p)

def paste_here(ctx: CommandContext, overwrite_mode: str = "skip"):
    path = _ctx_path(ctx)
    if not path:
        return
    a = os.path.abspath(path)
    d = a if os.path.isdir(a) else os.path.dirname(a)
    paster = ClipboardFilePaster()
    plans = paster.build_paste_plan(d)
    decisions = {plan.index: PasteDecision(mode=overwrite_mode if plan.conflict else "overwrite") for plan in plans}
    paster.execute_paste(plans, decisions)

class FileCommands:
    DEFAULT_MENU_ITEMS = [
        "file.open",
        "file.show_explorer",
        "-",
        "file.copy_path",
        "file.copy_path_list",
        "-",
        "file.cut",
        "file.copy",
        "file.delete",
        "-",
        "file.paste",
    ]
    COMMAND_DEFS = [
        CommandMeta(
            id="file.open",
            display="Open File",
            func=open_file,
        ),
        CommandMeta(
            id="file.show_explorer",
            display="Reveal in Explorer",
            func=show_in_explorer,
        ),
        CommandMeta(
            id="file.copy_path",
            display="Copy Path",
            func=copy_path,
        ),
        CommandMeta(
            id="file.copy_path_list",
            display="Copy Path List",
            func=copy_path_list,
        ),
        CommandMeta(
            id="file.copy",
            display="Copy",
            hotkey="Ctrl+C",
            func=copy_files,
        ),
        CommandMeta(
            id="file.cut",
            display="Cut",
            hotkey="Ctrl+X",
            func=cut_files,
        ),
        CommandMeta(
            id="file.delete",
            display="Delete",
            hotkey="Delete",
            has_options=True,
            params=[CommandParam(name="permanent", value=False, description="Delete permanently (bypass recycle bin)")],
            func=delete_files,
        ),
        CommandMeta(
            id="file.paste",
            display="Paste here",
            hotkey="Ctrl+V",
            has_options=True,
            params=[CommandParam(name="overwrite_mode", value=["skip", "overwrite", "rename"], description="Overwrite mode", default="skip")],
            func=paste_here,
        ),
    ]

    @classmethod
    def register_all(cls):
        register_command_defs(cls.COMMAND_DEFS)
