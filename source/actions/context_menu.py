import os
from PySide6 import QtCore, QtGui, QtWidgets

from .commandbase import CommandMenuBuilder
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
        def get_context():
            return {
                "path": path,
                "paths": self.get_selected_sources()
            }
        
        menu_items = [
            ":File",
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
        
        menu = self.command_builder.build(self.parent, menu_items, get_context)
        
        actions = menu.actions()
        copy_path_list_index = None
        for i, action in enumerate(actions):
            if action.data() == "file.copy_path_list":
                copy_path_list_index = i
                break
        
        if copy_path_list_index is not None:
            before = actions[copy_path_list_index + 1]
            self.command_builder.create_custom_action(
                menu,
                self.parent,
                self.t.tr("Copy FileName"),
                lambda: self.copy_path(path),
                before_action=before,
            )
            actions = menu.actions()
            menu.insertSeparator(actions[copy_path_list_index + 2])
            actions = menu.actions()
            before2 = actions[copy_path_list_index + 3]
            self.command_builder.create_custom_action(
                menu,
                self.parent,
                self.t.tr("Select Folder"),
                lambda: self.select_folder(path),
                before_action=before2,
            )
        
        return menu
    
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
        def get_context():
            return {"path": path}
        
        menu_items = [
            ":Path",
            "file.copy_path",
            "file.show_explorer",
            "---",
            "file.paste",
            "---",
        ]
        
        menu = self.command_builder.build(self.root, menu_items, get_context)
        
        if path in self.view.roots:
            self.command_builder.create_custom_action(
                menu,
                self.root,
                self.t.tr('Remove from view'),
                lambda: self.remove(path),
            )
        else:
            self.command_builder.create_custom_action(
                menu,
                self.root,
                self.t.tr('Ignore this folder'),
                lambda: self.ignore(path),
            )
        
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