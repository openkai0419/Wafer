import os
from PySide6 import QtWidgets, QtGui, QtCore

from ..viewer_settings import main_setting
from ...profiling import init_env
from ..thread import main_thread
from ...core.setting_db import SettingDB
logger, profiler = init_env()

class FolderContextMenuBuilder:
    def __init__(self, parent, db_name):
        self.view = parent
        self.settingdb = SettingDB(db_name)

    def build_menu(self, path: str) -> QtWidgets.QMenu:
        menu = QtWidgets.QMenu(self.view)
        menu.addAction("パスをコピー", lambda: self.copy_path(path))
        menu.addAction("エクスプローラーで開く", lambda: self.open_in_explorer(path))
        menu.addSeparator()
        if self.view.is_root_path(path):
            pass
            menu.addAction("除去", lambda: self.remove(path))
        else:
            menu.addAction("除外", lambda: self.ignore(path))
        return menu

    def open_in_explorer(self, path):
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))

    def copy_path(self, path):
        QtGui.QGuiApplication.clipboard().setText(path)

    def remove(self, path):
        if path in self.view.root_paths:
            self.settingdb.remove_parent_folder(path)
            self.view.remove_path(path)

    def ignore(self, path):
        self.settingdb.add_ignore_folder(path)