import os
from PySide6 import QtWidgets, QtGui, QtCore

from ..viewer_settings import main_setting
from ...profiling import init_env
from ..thread import main_thread
logger, profiler = init_env()

class FolderContextMenuBuilder:
    def __init__(self, parent=None):
        self.parent = parent

    def build_menu(self, path: str) -> QtWidgets.QMenu:
        menu = QtWidgets.QMenu(self.parent)
        menu.addAction("エクスプローラーで開く", lambda: self.open_in_explorer(path))
        menu.addAction("パスをコピー", lambda: self.copy_path(path))
        menu.addAction("ビューから除外", lambda: self.exclude(path))
        return menu

    def open_in_explorer(self, path):
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))

    def copy_path(self, path):
        QtGui.QGuiApplication.clipboard().setText(path)

    def exclude(self, path):
        print(f"Excluding path: {path}")  # ここで除外処理を呼び出す
