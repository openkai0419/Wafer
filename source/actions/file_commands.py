import os
import json
import sys
from typing import List, Optional, Callable, Dict, Any
from PySide6 import QtCore, QtGui, QtWidgets
from .commandbase import CommandMeta, CommandParam, register_command_defs, CommandMenuBuilder, CommandMenuSection
from ..os.copy import ClipboardFileTransfer
from ..os.paste import ClipboardFilePaster, PasteDecision
from ..common.profiling import logger, profiler

def open_file(path: str = None):
    if not path:
        return
    QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))

def show_in_explorer(path: str = None):
    if not path:
        return
    info = QtCore.QFileInfo(path)
    if not info.exists():
        return
    if sys.platform.startswith('win'):
        QtCore.QProcess.startDetached('explorer', ['/select,', QtCore.QDir.toNativeSeparators(info.absoluteFilePath())])
    else:
        QtCore.QProcess.startDetached('xdg-open', [info.absolutePath()])

def copy_path(path: str = None):
    if path is None:
        return
    QtGui.QGuiApplication.clipboard().setText(path)

def copy_path_list(paths: List[str] = None):
    if not paths:
        return
    QtGui.QGuiApplication.clipboard().setText(json.dumps(paths))

def copy_files(paths: List[str] = None):
    if not paths:
        return
    ClipboardFileTransfer().set_files(paths, cut=False)

def cut_files(paths: List[str] = None):
    if not paths:
        return
    ClipboardFileTransfer().set_files(paths, cut=True)

def delete_files(paths: List[str] = None, permanent: bool = False):
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

def paste_here(path: str = None, overwrite_mode: str = "skip"):
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
        "---",
        "file.copy_path",
        "file.copy_path_list",
        "---",
        "file.cut",
        "file.copy",
        "file.delete",
        "---",
        "file.paste",
    ]
    COMMAND_DEFS = [
        {
            "meta": CommandMeta(
                id="file.open",
                display="Open File",
                params=[CommandParam("path", str)],
                hotkey="Ctrl+F"
            ),
            "func": open_file,
        },
        {
            "meta": CommandMeta(
                id="file.show_explorer",
                display="Reveal in Explorer",
                params=[CommandParam("path", str)],
                hotkey="Ctrl+O"
            ),
            "func": show_in_explorer,
        },
        {
            "meta": CommandMeta(
                id="file.copy_path",
                display="Copy Path",
                params=[CommandParam("path", str)]
            ),
            "func": copy_path,
        },
        {
            "meta": CommandMeta(
                id="file.copy_path_list",
                display="Copy Path List",
                params=[CommandParam("paths", list)]
            ),
            "func": copy_path_list,
        },
        {
            "meta": CommandMeta(
                id="file.copy",
                display="Copy",
                params=[CommandParam("paths", list)],
                hotkey="Ctrl+C"
            ),
            "func": copy_files,
        },
        {
            "meta": CommandMeta(
                id="file.cut",
                display="Cut",
                params=[CommandParam("paths", list)],
                hotkey="Ctrl+X"
            ),
            "func": cut_files,
        },
        {
            "meta": CommandMeta(
                id="file.delete",
                display="Delete",
                params=[
                    CommandParam("paths", list),
                    CommandParam("permanent", bool, False, "Delete permanently (bypass recycle bin)")
                ],
                hotkey="Delete",
                undoable=True,
                has_options=True
            ),
            "func": delete_files,
        },
        {
            "meta": CommandMeta(
                id="file.paste",
                display="Paste here",
                params=[
                    CommandParam("path", str),
                    CommandParam("overwrite_mode", str, "skip", "Overwrite mode", choices=["skip", "overwrite", "rename"])
                ],
                hotkey="Ctrl+V",
                has_options=True
            ),
            "func": paste_here,
        },
    ]

    @classmethod
    def register_all(cls):
        register_command_defs(cls.COMMAND_DEFS)

    @classmethod
    def as_section(cls, title: str = "File", context_provider: Optional[Callable[[], Dict[str, Any]]] = None) -> CommandMenuSection:
        return CommandMenuSection(title, cls.DEFAULT_MENU_ITEMS, context_provider)

    @classmethod
    def build_menu(
        cls,
        parent: QtWidgets.QWidget,
        title: str = "File",
        context_provider: Optional[Callable[[], Dict[str, Any]]] = None,
        items: Optional[List[str]] = None,
    ) -> QtWidgets.QMenu:
        m = QtWidgets.QMenu(title, parent)
        CommandMenuBuilder().build_into(m, parent, items or cls.DEFAULT_MENU_ITEMS, context_provider)
        return m