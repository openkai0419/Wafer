import contextlib
from ..common.funcs import get_data_db, get_setting_db
from ..common.profiling import logger, profiler
from ..db.collector import ImageIndexer
from ..db.db_utils import clean_database, delete_database_files
from ..db.setting_db import SettingDB
from ..zmq.zmq import Role, ZMQNode
from .progress_notifier import close_publisher, set_node
from .watch_folder import WatchFolder
from .watch_setting import SettingWatcher

class CollectorProcess:

    def __init__(self, name):
        super().__init__()
        self.dname = name
        self.setting_db = None
        self.data_db = None
        self.folders_to_watch = []
        self.zmq = ZMQNode(Role.COLLECTOR, on_message=self.on_message)
        self.zmq.start()
        set_node(self.zmq)

    def on_message(self, v):
        table = v.table
        topic = v.topic
        message = v.message
        logger.info(f'NOTIFY : {table} {topic} {message}')
        handlers = {"cleanup": lambda: self.cleanup(),
                    "rescan": lambda: self.rescan()}
        try:
            handlers.get(topic, lambda: None)()
        except Exception:
            logger.exception('Error processing IPC message: %s', v)

    @profiler.profile
    def start_watch(self):
        self.setting_db = SettingDB(get_setting_db(self.dname))
        self.data_db = ImageIndexer(get_data_db(self.dname))
        self.data_db.set_exclude_paths(self.setting_db.get_all_ignore_folders())
        if self.setting_db.get_kv('deleteflag', False) == True:
            self.delete()
            return
        with self.data_db as indexer:
            indexer.check_init()
        self.folder_watcher = WatchFolder(self.dname, self.data_db)
        folders = self.setting_db.get_all_parent_folders()
        self.folders_to_watch = folders
        self.folder_watcher.start(folders)
        self.setting_watcher = SettingWatcher(self.setting_db)
        self.setting_watcher.parentFoldersChanged.connect(self.reload_parent_folder)
        self.setting_watcher.ignoreFoldersChanged.connect(self.reload_ignore_folder)
        self.setting_watcher.deleteFlagEmit.connect(self.delete)
        self.setting_watcher.start()
        logger.debug('tray app start watching end')

    def rescan(self):
        if self.folder_watcher:
            self.folder_watcher.rescan_all()

    @profiler.profile
    def reload_parent_folder(self, folderlist):
        logger.debug(f'parent folder {folderlist}')
        self.folders_to_watch = folderlist
        self.folder_watcher.start(folderlist)

    @profiler.profile
    def reload_ignore_folder(self, folderlist):
        logger.debug(f'ignore folder {folderlist}')
        self.folder_watcher.set_ignore(folderlist)

    def cleanup(self):
        self.folder_watcher.clean()

    def delete(self):
        self.stop()
        delete_database_files(self.setting_db.db_name, force=True)
        delete_database_files(self.data_db.db_path, force=True)
        clean_database()

    def stop(self):
        if hasattr(self, 'folder_watcher') and self.folder_watcher:
            self.folder_watcher.stop()
        if hasattr(self, 'setting_watcher') and self.setting_watcher:
            self.setting_watcher.stop()
        try:
            close_publisher()
        except Exception as e:
            logger.debug(f'close_publisher failed: {e}')

    def quit(self):
        self.stop()
