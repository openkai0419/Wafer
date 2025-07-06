from PySide6 import QtWidgets, QtGui, QtCore

from ...common import normalize_path
from ...profiling import logger, profiler
from ...dialog import ConfirmDialog
from ...settings.translation import TranslatorMixin

class FolderContextMenuBuilder(TranslatorMixin):
    def __init__(self, parent, root):
        self.view = parent
        self.root = root

    def build_menu(self, path: str) -> QtWidgets.QMenu:
        menu = QtWidgets.QMenu(self.view)
        menu.addAction(self.t.tr("Copy Path"), lambda: self.copy_path(path))
        menu.addAction(self.t.tr("Open in Explorer"), lambda: self.open_in_explorer(path))
        menu.addSeparator()
        logger.info(self.view.roots)
        logger.info(path in self.view.roots)
        if path in self.view.roots:
            menu.addAction(self.t.tr("Remove"), lambda: self.remove(path))
        else:
            menu.addAction(self.t.tr("Ignore"), lambda: self.ignore(path))
        return menu

    def open_in_explorer(self, path):
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))

    def copy_path(self, path):
        QtGui.QGuiApplication.clipboard().setText(path)

    def remove(self, path):
        result = ConfirmDialog.ask(self.t.trf("Remove from view list?\n{path}", path=path),
                                   title=self.t.tr("Confirm"),
                                   buttons=(self.t.tr("Remove"), self.t.tr("Cancel")), parent=self.view)
        if result == self.t.tr("Remove"):
            if path in self.view.roots:
                self.view.remove_root(path)
                self.root.setting_db.remove_parent_folder(path)

    def ignore(self, path):
        result = ConfirmDialog.ask(self.t.trf("Exclude from view list?\n{path}", path=path),
                                   title=self.t.tr("Confirm"),
                                   buttons=(self.t.tr("Exclude"), self.t.tr("Cancel")), parent=self.view)
        if result == self.t.tr("Exclude"):
            path = normalize_path(path)
            self.view.add_excluded(path)
            self.root.setting_db.add_ignore_folder(path)
        
