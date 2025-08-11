from ..common.profiling import logger, profiler
from ..common.funcs import get_data_db, get_setting_db
from ..db.collector import ImageIndexer
from .watch_folder import WatchFolder
from ..db.setting_db import SettingDB
from .watch_setting import SettingWatcher
from ..db.db_utils import delete_database_files, clean_database
from ..zmq.broker import ZMQNode, Role

class CollectorProcess():
    def __init__(self, name):
        super().__init__()
        logger.info("FOLDER WATCHER EXECUTED")
        self.dname = name

        self.setting_db = None
        self.data_db = None

        self.folders_to_watch = []
        self.zmq = ZMQNode(Role.COLLECTOR, on_message=self.on_message)
        self.zmq.start()

        self.start_watch()
    
    def on_message(self, var):
        logger.info(var)

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

    def cleanup(self):
        self.folder_watcher.clean()

    def delete(self):
        self.stop()
        delete_database_files(self.setting_db.db_name, force=True)
        delete_database_files(self.data_db.db_path, force=True)
        clean_database()
    
    def stop(self):
        if hasattr(self, "folder_watcher") and self.folder_watcher:
            self.folder_watcher.stop()
        if hasattr(self, "setting_watcher")and self.setting_watcher:
            self.setting_watcher.stop()

    def quit(self):
        pass