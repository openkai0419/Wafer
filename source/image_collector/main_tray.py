from PySide6 import QtWidgets, QtGui, QtCore

from ..profiling import init_env
from .watch_folder import WatchFolder
logger, profiler = init_env()

class TrayApp(QtWidgets.QSystemTrayIcon):
    def __init__(self, icon, folders_to_watch, parent=None):
        super().__init__(icon, parent)
        logger.info("FOLDER WATCHER EXECUTED")
        self.setToolTip("Folder Watcher")
        self.folders_to_watch = folders_to_watch

        self.menu = QtWidgets.QMenu()
        self.quit_action = self.menu.addAction("終了")
        self.quit_action.triggered.connect(self.quit)

        self.setContextMenu(self.menu)
        self.activated.connect(self.on_activated)

        self.folder_watcher = WatchFolder()
        self.folder_watcher.start(self.folders_to_watch)
        self.folder_watcher.event_batcher.folder_changed.connect(self.on_path_changed)

        QtCore.QTimer.singleShot(0, lambda: self.folder_watcher.rescan_all(self.folders_to_watch))

    def on_path_changed(self):
        pass

    def on_activated(self, reason):
        if reason == QtWidgets.QSystemTrayIcon.Trigger:
            QtWidgets.QMessageBox.information(None, "監視中", f"監視対象:\n" + "\n".join(self.folders_to_watch))

    def quit(self):
        QtWidgets.QApplication.quit()
        self.folder_watcher.quit()
