import json
import os
import sys
from PySide6 import QtCore, QtGui, QtWidgets
from ..common.funcs import normalize_path, uipx
from ..image_setting.translation import TranslatorMixin
from ..os.copy import ClipboardFileTransfer
from ..os.paste import ClipboardFilePaster, PasteDecision
from ..qt.dialog import ConfirmDialog

def create_labeled_separator(label, parent):
    action = QtWidgets.QWidgetAction(parent)
    widget = QtWidgets.QWidget(parent)
    layout = QtWidgets.QHBoxLayout(widget)
    space = uipx(10)
    layout.setContentsMargins(space * 1.6, space / 4, space * 1.6, 0)
    lbl = QtWidgets.QLabel(label)
    lbl.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
    lbl.setStyleSheet('color: gray; font-size: {}px;'.format(space))
    lbl.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Maximum)
    layout.addWidget(lbl)
    action.setDefaultWidget(widget)
    return action

def add_menu_actions_recursively(widget, menu):
    for action in menu.actions():
        if action.menu():
            add_menu_actions_recursively(widget, action.menu())
        else:
            widget.addAction(action)

class MenuBuilder:

    def build(self, root_menu, definitions, parent):
        actions = {}
        menus = {}
        for item in definitions:
            path = item['path'].split('/')
            name = path[-1]
            parent_path = '/'.join(path[:-1])
            menu = self._get_or_create_menu(root_menu, parent_path, menus, parent)
            action = QtGui.QAction(name, parent)
            if item.get('separator'):
                if name == '':
                    menu.addSeparator()
                else:
                    sep_action = create_labeled_separator(name, parent)
                    menu.addAction(sep_action)
                continue
            if 'shortcut' in item:
                action.setShortcut(item['shortcut'])
            if 'checkable' in item:
                action.setCheckable(True)
            if 'callback' in item:
                action.triggered.connect(item['callback'])
            menu.addAction(action)
            actions[item['path']] = action
        return (actions, menus)

    def _get_or_create_menu(self, root_menu, path, menus, parent):
        if not path:
            return root_menu
        if path in menus:
            return menus[path]
        parts = path.split('/')
        cur_path = ''
        parent_menu = root_menu
        for part in parts:
            cur_path = (cur_path + '/' + part).lstrip('/')
            if cur_path not in menus:
                menu = QtWidgets.QMenu(part, parent)
                parent_menu.addMenu(menu)
                menus[cur_path] = menu
            parent_menu = menus[cur_path]
        return menus[path]

class ActionManager(TranslatorMixin):

    def __init__(self):
        self.builder = MenuBuilder()

    @staticmethod
    def run_in_explorer(path):
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))

    @staticmethod
    def show_in_explorer(path):
        info = QtCore.QFileInfo(path)
        if not info.exists():
            return
        if sys.platform.startswith('win'):
            QtCore.QProcess.startDetached('explorer', ['/select,', QtCore.QDir.toNativeSeparators(info.absoluteFilePath())])
        else:
            QtCore.QProcess.startDetached('xdg-open', [info.absolutePath()])

    @staticmethod
    def copy_path(path):
        QtGui.QGuiApplication.clipboard().setText(path)

    @staticmethod
    def copy_path_list(path):
        QtGui.QGuiApplication.clipboard().setText(json.dumps(path))

    @staticmethod
    def set_copy_file(paths):
        ClipboardFileTransfer().set_files(paths, cut=False)

    @staticmethod
    def set_cut_file(paths):
        ClipboardFileTransfer().set_files(paths, cut=True)

    @staticmethod
    def delete_file(file_paths):
        for path in file_paths:
            try:
                if not os.path.exists(path):
                    continue
                if not os.path.isfile(path) and (not os.path.islink(path)):
                    continue
                os.remove(path)
            except Exception as e:
                raise

    @staticmethod
    def get_directory_from_path(path):
        abs_path = os.path.abspath(path)
        if os.path.isdir(abs_path):
            return abs_path
        else:
            return os.path.dirname(abs_path)
    
    @staticmethod
    def paste_here(path):
        paster = ClipboardFilePaster()
        plans = paster.build_paste_plan(ActionManager.get_directory_from_path(path))
        descs = {}
        for plan in plans:
            if plan.conflict:
                descs[plan.index] = PasteDecision(mode="skip")
            else:
                descs[plan.index] = PasteDecision(mode="overwrite")
        paster.execute_paste(plans, descs)

class ContextMenuBuilder(ActionManager):

    def __init__(self, parent=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.parent = parent

    def build_menu(self, path):
        menu = QtWidgets.QMenu(self.parent)
        justified_menus = [
            {'path': self.t.tr('File'), 'separator': True},
            {'path': self.t.tr('Open File'), 'shortcut': 'Ctrl+F','callback': lambda: self.run_in_explorer(path),},
            {'path': self.t.tr('Reveal in Explorer'),'shortcut': 'Ctrl+O','callback': lambda: self.show_in_explorer(path),},
            {'path': self.t.tr(''), 'separator': True},
            {'path': self.t.tr('Copy Path'),'shortcut': '','callback': lambda: self.copy_path(path),},
            {'path': self.t.tr('Copy Path List'),'shortcut': '','callback': lambda: self.copy_path_list(self.get_selected_sources()),},
            {'path': self.t.tr('Copy FileName'),'shortcut': '','callback': lambda: self.copy_path(path),},
            {'path': self.t.tr(''), 'separator': True},
            {'path': self.t.tr('Select Folder'),'shortcut': '','callback': lambda: self.select_folder(path),},
            {'path': self.t.tr(''), 'separator': True},
            {'path': self.t.tr('Cut'),'shortcut': 'Ctrl+X','callback': lambda: self.set_cut_file(self.get_selected_sources()),},
            {'path': self.t.tr('Copy'),'shortcut': 'Ctrl+C','callback': lambda: self.set_copy_file(self.get_selected_sources()),},
            {'path': self.t.tr('Delete'),'shortcut': 'Delete','callback': lambda: self.delete_file(self.get_selected_sources()),},
            {'path': self.t.tr(''), 'separator': True},
            {'path': self.t.tr('Paste here'),'shortcut': 'Ctrl+V','callback': lambda: self.paste_here(path),},
        ]
        self.builder.build(menu, justified_menus, parent=self.parent)
        return menu

    def select_folder(self, path):
        path = self.get_directory_from_path(path)
        self.parent.folder_view.expand_and_select_path(path)
    
    def get_selected_sources(self):
        return self.parent.content.get_selected_sources()

class FolderContextMenuBuilder(ActionManager):

    def __init__(self, parent, root, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.root = root
        self.view = parent

    def build_menu(self, path):
        menu = QtWidgets.QMenu(self.root)
        menus = [
            {'path': self.t.tr('Path'), 'separator': True},
            {'path': self.t.tr('Copy Path'),'shortcut': 'Ctrl+C','callback': lambda: self.copy_path(path),},
            {'path': self.t.tr('Reveal in Explorer'),'shortcut': 'Ctrl+O','callback': lambda: self.show_in_explorer(path),},
            {'path': self.t.tr(''), 'separator': True},
            {'path': self.t.tr('Paste here'),'shortcut': 'Ctrl+V','callback': lambda: self.paste_here(path),},
            {'path': self.t.tr(''), 'separator': True},
        ]
        if path in self.view.roots:
            menus.append({"path": self.t.tr('Remove from view'),"callback": lambda: self.remove(path)})
        else:
            menus.append({"path": self.t.tr('Ignore this folder'), "callback": lambda: self.ignore(path)})
        self.builder.build(menu, menus, parent=self.root)

        return menu

    def remove(self, path):
        result = ConfirmDialog.ask(self.t.trf('Are you sure to Remove this folder?  (This does not delete folders)\\  {path}', path=path), title=self.t.tr('Confirm'), buttons=(self.t.tr('Remove'), self.t.tr('Cancel')), parent=self.view)
        if result == self.t.tr('Remove'):
            if path in self.view.roots:
                self.view.remove_root(path)
                self.root.setting_db.remove_parent_folder(path)

    def ignore(self, path):
        result = ConfirmDialog.ask(self.t.trf('Are you sure to Ingore this folder?  (This does not delete folders)\n  {path}', path=path), title=self.t.tr('Confirm'), buttons=(self.t.tr('Ignore'), self.t.tr('Cancel')), parent=self.view)
        if result == self.t.tr('Ignore'):
            path = normalize_path(path)
            self.view.add_excluded(path)
            self.root.setting_db.add_ignore_folder(path)
