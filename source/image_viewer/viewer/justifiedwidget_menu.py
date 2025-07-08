from PySide6 import QtWidgets, QtGui, QtCore

from ...profiling import logger, profiler
from ...settings.translation import TranslatorMixin

class ViewerContextMenuBuilder(TranslatorMixin):
    def __init__(self, parent, root):
        self.view = parent
        self.root = root

    def build_menu(self, path: str) -> QtWidgets.QMenu:
        menu = QtWidgets.QMenu(self.view)
        menu.addAction(self.t.tr("Copy Path"), lambda: self.copy_path(path))
        menu.addAction(self.t.tr("Open in Explorer"), lambda: self.open_in_explorer(path))
        menu.addSeparator()
        return menu

    def open_in_explorer(self, path):
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))

    def copy_path(self, path):
        QtGui.QGuiApplication.clipboard().setText(path)