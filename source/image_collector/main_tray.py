from PySide6 import QtWidgets, QtGui, QtCore

from ..profiling import logger, profiler
from ..debounce import qt_debounce
from ..common import get_data_db, get_setting_db, run_side_subprocess, get_setting_file_name
from ..core.collector import ImageIndexer
from .watch_folder import WatchFolder
from .watch_setting import SettingWatcher
from .progress_notifier import close_publisher, get_viewer_count, send_show_toggle
from ..core.setting_db import SettingDB
from ..dialog import ConfirmDialog 
from ..constants import APP_NAME


class TrayApp(QtWidgets.QSystemTrayIcon):
    @profiler.profile
    def __init__(self, icon, name, parent=None):
        super().__init__(icon, parent)
        logger.info("FOLDER WATCHER EXECUTED")
        self.setToolTip(f"{APP_NAME} : {name}")
        self.dname = name

        self.menu = QtWidgets.QMenu()
        self.show_state = False
        self.dummy_parent = QtWidgets.QApplication.activeWindow()

        self.show_action = self.menu.addAction("ウィンドウを表示")
        self.show_action.triggered.connect(self.show_if_not)
        self.show_action = self.menu.addAction("新規ウィンドウを開く")
        self.show_action.triggered.connect(self.show_anyways)
        self.menu.addSeparator()
        self.test_action = self.menu.addAction("テスト")
        self.test_action.triggered.connect(self.test)
        self.menu.addSeparator()
        self.quit_action = self.menu.addAction("終了")
        self.quit_action.triggered.connect(self.quit)

        self.setContextMenu(self.menu)
        self.folders_to_watch = []
        self.activated.connect(self.on_activated)

        QtWidgets.QApplication.instance().aboutToQuit.connect(self.cleanup)
        QtCore.QTimer.singleShot(0, self.start_watch)
    
    @profiler.profile
    def start_watch(self):
        self.setting_db = SettingDB(get_setting_db(self.dname))
        self.data_db = ImageIndexer(get_data_db(self.dname))
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

    @profiler.profile
    def on_activated(self, reason):
        if reason == QtWidgets.QSystemTrayIcon.Trigger:
            self.show_if_not()

    @qt_debounce(10)
    def show_if_not(self):
        c = get_viewer_count()
        logger.info(c)
        if c < 1:
            self.show_anyways()
        else:
            self.show_state = not self.show_state
            send_show_toggle(self.show_state)
    
    @qt_debounce(1000)
    def show_anyways(self):
        run_side_subprocess("main")

    def test(self):
        f = get_setting_file_name()
        c = ConfirmDialog.ask(f"{f}", buttons=("ok", "none", "cancel"))

    def cleanup(self):
        if hasattr(self, "folder_watcher"):
            self.folder_watcher.quit()
        if hasattr(self, "setting_watcher"):
            self.setting_watcher.stop()
            close_publisher()

    def quit(self):
        QtWidgets.QApplication.quit()
