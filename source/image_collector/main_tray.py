from PySide6 import QtWidgets, QtGui, QtCore

from ..profiling import init_env
from ..constants import setting_db_name, data_db_name
from .watch_folder import WatchFolder
from .watch_setting import SettingWatcher
from ..core.setting_db import SettingDB

logger, profiler = init_env()

class TrayApp(QtWidgets.QSystemTrayIcon):
    @profiler.profile
    def __init__(self, icon, parent=None):
        super().__init__(icon, parent)
        logger.info("FOLDER WATCHER EXECUTED")
        self.setToolTip("Folder Watcher")

        self.db = SettingDB(setting_db_name)
        self.folders_to_watch = self.db.get_all_parent_folders()
        self.folders_to_ignore = self.db.get_all_ignore_folders()

        self.menu = QtWidgets.QMenu()
        self.quit_action = self.menu.addAction("終了")
        self.quit_action.triggered.connect(self.quit)

        self.setContextMenu(self.menu)
        self.activated.connect(self.on_activated)

        self.folder_watcher = WatchFolder(data_db_name)
        self.folder_watcher.set_ignore_folders(self.folders_to_ignore)
        self.folder_watcher.start(self.folders_to_watch)

        self.setting_watcher = SettingWatcher(self.db.db_name)
        self.setting_watcher.parentFoldersChanged.connect(self.reload_parent_folder)
        self.setting_watcher.ignoreFoldersChanged.connect(self.reload_ignore_folder)
        self.setting_watcher.start()
        logger.info("TrayApp init end")
    
    @profiler.profile
    def reload_parent_folder(self, folderlist):
        logger.info(f"parent folder {folderlist}")
        self.folder_watcher.start(folderlist)

    @profiler.profile
    def reload_ignore_folder(self, folderlist):
        logger.info(f"ignore folder {folderlist}")
        self.folder_watcher.set_ignore_folders(folderlist)

    def on_activated(self, reason):
        if reason == QtWidgets.QSystemTrayIcon.Trigger:
            QtWidgets.QMessageBox.information(None, "監視中", f"監視対象:\n" + "\n".join(self.folders_to_watch))

    def quit(self):
        QtWidgets.QApplication.quit()
