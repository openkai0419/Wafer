from PySide6 import QtWidgets, QtGui, QtCore

from ..profiling import logger, profiler
from ..debounce import qt_debounce
from ..common import get_data_db, get_setting_db, new_main, get_setting_file_names
from ..core.collector import ImageIndexer
from .watch_folder import WatchFolder
from .watch_setting import SettingWatcher
from .progress_notifier import close_publisher, get_viewer_count, send_show_toggle
from ..core.setting_db import SettingDB
from ..dialog import ConfirmDialog 
from ..constants import APP_FILE_NAME, APP_NAME
from ..core.db_utils import delete_database_files, clean_database
from ..settings.translation import TranslatorMixin


class TrayApp(QtWidgets.QSystemTrayIcon, TranslatorMixin):
    @profiler.profile
    def __init__(self, icon, name, parent=None):
        super().__init__(icon, parent)
        logger.info("FOLDER WATCHER EXECUTED")
        self.setToolTip(f"{APP_NAME} : {name}")
        self.dname = name

        self.menu = QtWidgets.QMenu()
        self.show_state = False

        self.setting_db = None
        self.data_db = None

        self.show_action = self.menu.addAction(self.t.tr("Show Window"))
        self.show_action.triggered.connect(self.show_if_not)
        self.show_action = self.menu.addAction(self.t.tr("Open New Window"))
        self.show_action.triggered.connect(self.show_anyways)
        self.menu.addSeparator()
        self.reload_action = self.menu.addAction(self.t.tr("ReScan All"))
        self.reload_action.triggered.connect(self.rescan)
        self.menu.addSeparator()
        self.test_action = self.menu.addAction(self.t.tr("Test"))
        self.test_action.triggered.connect(self.test)
        self.menu.addSeparator()
        self.quit_action = self.menu.addAction(self.t.tr("Quit"))
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
        if self.setting_db.get_kv("deleteflag", False) == True:
            self.delete()
            return
        with self.data_db as indexer:
            indexer.check_init()

        self.folder_watcher = WatchFolder(self.dname, self.data_db)
        folders = self.setting_db.get_all_parent_folders()
        logger.info(folders)
        self.folder_watcher.start(folders)
        self.folders_to_watch = folders

        self.setting_watcher = SettingWatcher(self.setting_db)
        self.setting_watcher.parentFoldersChanged.connect(self.reload_parent_folder)
        self.setting_watcher.ignoreFoldersChanged.connect(self.reload_ignore_folder)
        self.setting_watcher.deleteFlagEmit.connect(self.delete)
        self.setting_watcher.start()
        logger.debug("tray app start watching end")
    
    def rescan(self):
        if self.folder_watcher:
            self.folder_watcher.rescan_all()

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
    
    @qt_debounce(500)
    def show_anyways(self):
        new_main("--viewer")

    def test(self):
        f = get_setting_file_names()
        c = ConfirmDialog.ask(f"{f}", buttons=("ok", "none", "cancel"))

    def cleanup(self, clean=True):
        if hasattr(self, "folder_watcher") and self.folder_watcher:
            self.folder_watcher.quit(clean)
        if hasattr(self, "setting_watcher")and self.setting_watcher:
            self.setting_watcher.stop()
            close_publisher()
        try:
            self.t.dump_missing_keys()
        except:
            pass

    def delete(self):
        self.cleanup(False)
        self.folder_watcher = None
        self.setting_watcher = None
        delete_database_files(self.setting_db.db_name, force=True)
        delete_database_files(self.data_db.db_path, force=True)
        clean_database()
        QtWidgets.QApplication.quit()

    def quit(self):
        QtWidgets.QApplication.quit()
