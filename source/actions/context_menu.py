import os
from PySide6 import QtCore, QtGui, QtWidgets

from .command.ui import CommandMenuBuilder
from .command.context import CommandContext
from .file_commands import FileCommands
from ..common.funcs import normalize_path
from ..lang.manager import TranslatorMixin
from ..qt.dialog import ConfirmDialog
from ..common.profiling import logger, profiler

FileCommands.register_all()

class ActionManager(TranslatorMixin):

    def __init__(self):
        self.command_builder = CommandMenuBuilder()
    
    @staticmethod
    def get_directory_from_path(path):
        abs_path = os.path.abspath(path)
        return abs_path if os.path.isdir(abs_path) else os.path.dirname(abs_path)

class ContextMenuBuilder(ActionManager):

    def __init__(self, parent=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.parent = parent

    def build_menu(self, path):
        menu_items = [
            ":File",
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

        seed_ctx = CommandContext.create(self.parent, "*", source="menu", extras={"path": path, "paths": self.get_selected_sources()})
        menu = QtWidgets.QMenu(self.parent)
        menu.setProperty("__CommandMenuBuilder_Menu__", True)
        self.command_builder.build_into(menu, self.parent, menu_items, seed_ctx=seed_ctx)
        self._insert_extras(menu, path)
        return menu

    def _insert_extras(self, menu: QtWidgets.QMenu, path: str):
        actions = menu.actions()
        idx = next((i for i, a in enumerate(actions) if str(a.data()) == "file.copy_path_list"), None)
        if idx is None:
            return
        before = actions[idx + 1] if idx + 1 < len(actions) else None
        act1 = QtGui.QAction(self.t.tr("Copy FileName"), menu)
        act1.triggered.connect(lambda: self.copy_path(path))
        menu.insertAction(before, act1) if before is not None else menu.addAction(act1)
        actions = menu.actions()
        idx2 = next((i for i, a in enumerate(actions) if str(a.data()) == "file.copy_path_list"), None)
        before_sep = actions[idx2 + 2] if idx2 is not None and idx2 + 2 < len(actions) else None
        menu.insertSeparator(before_sep) if before_sep is not None else menu.addSeparator()
        actions = menu.actions()
        before2 = actions[idx2 + 3] if idx2 is not None and idx2 + 3 < len(actions) else None
        act2 = QtGui.QAction(self.t.tr("Select Folder"), menu)
        act2.triggered.connect(lambda: self.select_folder(path))
        menu.insertAction(before2, act2) if before2 is not None else menu.addAction(act2)
    
    def copy_path(self, path):
        QtGui.QGuiApplication.clipboard().setText(path)

    def select_folder(self, path):
        folder = self.get_directory_from_path(path)
        self.parent.folder_view.expand_and_select_path(folder)
    
    def get_selected_sources(self):
        return self.parent.content.get_selected_sources()

class FolderContextMenuBuilder(ActionManager):

    def __init__(self, parent, root, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.root = root
        self.view = parent

    def build_menu(self, path):
        menu_items = [
            ":Path",
            "file.copy_path",
            "file.show_explorer",
            "-",
            "file.paste",
            "-",
        ]

        seed_ctx = CommandContext.create(self.root, "*", source="menu", extras={"path": path})
        menu = QtWidgets.QMenu(self.root)
        menu.setProperty("__CommandMenuBuilder_Menu__", True)
        self.command_builder.build_into(menu, self.root, menu_items, seed_ctx=seed_ctx)
        if path in self.view.roots:
            a = menu.addAction(self.t.tr("Remove from view"))
            a.triggered.connect(lambda: self.remove(path))
        else:
            a = menu.addAction(self.t.tr("Ignore this folder"))
            a.triggered.connect(lambda: self.ignore(path))
        return menu

    def remove(self, path):
        result = ConfirmDialog.ask(
            self.t.trf('Are you sure to Remove this folder?  (This does not delete folders)\\  {path}', path=path), 
            title=self.t.tr('Confirm'), 
            buttons=(self.t.tr('Remove'), self.t.tr('Cancel')), 
            parent=self.view
        )
        if result == self.t.tr('Remove'):
            if path in self.view.roots:
                self.view.remove_root(path)
                self.root.setting_db.remove_parent_folder(path)

    def ignore(self, path):
        result = ConfirmDialog.ask(
            self.t.trf('Are you sure to Ingore this folder?  (This does not delete folders)\n  {path}', path=path), 
            title=self.t.tr('Confirm'), 
            buttons=(self.t.tr('Ignore'), self.t.tr('Cancel')), 
            parent=self.view
        )
        if result == self.t.tr('Ignore'):
            path = normalize_path(path)
            self.view.add_excluded(path)
            self.root.setting_db.add_ignore_folder(path)