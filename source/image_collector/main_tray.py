from PySide6 import QtWidgets, QtGui, QtCore
import atexit

from ..profiling import logger, profiler
from ..constants import get_data_db, get_setting_db
from ..core.collector import ImageIndexer
from .watch_folder import WatchFolder
from .watch_setting import SettingWatcher
from .progress_notifier import close_publisher, get_viewer_count
from ..core.setting_db import SettingDB


class TrayApp(QtWidgets.QSystemTrayIcon):
    @profiler.profile
    def __init__(self, icon, name, parent=None):
        super().__init__(icon, parent)
        logger.info("FOLDER WATCHER EXECUTED")
        self.setToolTip("Folder Watcher")

        self.menu = QtWidgets.QMenu()

        self.show_action = self.menu.addAction("表示")
        self.show_action.triggered.connect(self.show_if_not)

        self.quit_action = self.menu.addAction("終了")
        self.quit_action.triggered.connect(self.quit)

        self.setContextMenu(self.menu)
        self.folders_to_watch = []
        self.activated.connect(self.on_activated)

        self.start_watch(get_setting_db(name), get_data_db(name))
        atexit.register(self.quit)
    
    def start_watch(self, setting_name, data_name):
        self.setting_db = SettingDB(setting_name)
        self.data_db = ImageIndexer(data_name)
        self.data_db.set_exclude_paths(self.setting_db.get_all_ignore_folders())
        with self.data_db as indexer:
            indexer.check_init()

        self.folder_watcher = WatchFolder(self.data_db)
        folders = self.setting_db.get_all_parent_folders()
        self.folder_watcher.start(folders)
        self.folders_to_watch = folders

        self.setting_watcher = SettingWatcher(self.setting_db)
        self.setting_watcher.parentFoldersChanged.connect(self.reload_parent_folder)
        self.setting_watcher.ignoreFoldersChanged.connect(self.reload_ignore_folder)
        self.setting_watcher.start()
        logger.debug("tray app start watching end")
    
    @profiler.profile
    def reload_parent_folder(self, folderlist):
        logger.debug(f"parent folder {folderlist}")
        self.folder_watcher.start(folderlist)
        self.folders_to_watch = folderlist

    @profiler.profile
    def reload_ignore_folder(self, folderlist):
        logger.debug(f"ignore folder {folderlist}")
        self.folder_watcher.set_ignore_folders(folderlist)

    def on_activated(self, reason):
        if reason == QtWidgets.QSystemTrayIcon.Trigger:
            QtWidgets.QMessageBox.information(None, "監視中", f"監視対象:\n" + "\n".join(self.folders_to_watch))

    def show_if_not(self):
        c = get_viewer_count()
        from ..dialog import ConfirmDialog
        logger.info(c)
        v = ConfirmDialog.ask(f"{c}", buttons=("ok", "no"))
        print(v)
        if c < 1:
            pass

    def quit(self):
        if hasattr(self, "folder_watcher"):
            self.folder_watcher.quit()
        if hasattr(self, "setting_watcher"):
            self.setting_watcher.stop()
            close_publisher()
        QtWidgets.QApplication.quit()
