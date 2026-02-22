from ..common.funcs import get_data_db, get_setting_db
from ..common.profiling import profiler
from ..common.logs import AppLogger
from ..db.indexer import FileIndexer
from ..db.db_utils import clean_database, delete_database_files
from ..db.setting_db import SettingDB
from ..io.collector import get_collector_info
from ..zmq.node import Node
from .dispatcher import CollectorDispatcher
from .progress_notifier import ProgressAggregator
from .watch_folder import WatchFolder
from .watch_setting import SettingWatcher
from .writer import CollectionWriter


class IndexerProcess:

    def __init__(self, name):
        self.dname = name
        self.setting_db = None
        self.data_db = None
        self.folder_watcher = None
        self.setting_watcher = None
        self.dispatcher = None
        self.writer = None
        self.zmq = Node('indexer', db=name, consumer=True)
        self.zmq.on('cleanup', lambda msg: self.cleanup() or True)
        self.zmq.on('rescan', lambda msg: self.rescan() or True)
        self.zmq.start()
        AppLogger.set_node(self.zmq, role='indexer')

    @profiler.profile
    def start_watch(self):
        AppLogger.info(f'indexer start_watch: {self.dname}')
        self.setting_db = SettingDB(get_setting_db(self.dname))
        self.data_db = FileIndexer(get_data_db(self.dname), collectors=get_collector_info())
        self.data_db.set_exclude_paths(self.setting_db.get_all_ignore_folders())
        if self.setting_db.get_kv('deleteflag', False) == True:
            self.delete()
            return
        with self.data_db as indexer:
            indexer.check_init()

        progress = ProgressAggregator(self.dname, self.zmq)

        self.writer = CollectionWriter(get_data_db(self.dname), progress)
        self.zmq.on('collect.result', self.writer.handle_result)
        self.writer.start()

        self.dispatcher = CollectorDispatcher(self.dname, self.data_db)
        self.dispatcher.start(self.zmq)

        self.folder_watcher = WatchFolder(self.data_db, progress)
        self.folder_watcher.start(self.setting_db.get_all_parent_folders())
        self.setting_watcher = SettingWatcher(self.setting_db)
        self.setting_watcher.parentFoldersChanged.connect(self.folder_watcher.start)
        self.setting_watcher.ignoreFoldersChanged.connect(self.folder_watcher.set_ignore)
        self.setting_watcher.deleteFlagEmit.connect(self.delete)
        self.setting_watcher.start()

    def rescan(self):
        if self.folder_watcher:
            self.folder_watcher.rescan_all()

    def cleanup(self):
        if self.folder_watcher:
            self.folder_watcher.clean()

    def delete(self):
        AppLogger.info(f'indexer delete: {self.dname}')
        self.stop()
        delete_database_files(self.setting_db.db_name, force=True)
        delete_database_files(self.data_db.db_path, force=True)
        clean_database()

    def stop(self):
        AppLogger.info(f'indexer stop: {self.dname}')
        if self.dispatcher:
            self.dispatcher.stop()
        if self.writer:
            self.writer.stop()
        if self.folder_watcher:
            self.folder_watcher.stop()
        if self.setting_watcher:
            self.setting_watcher.stop()
        try:
            self.zmq.stop()
        except Exception as e:
            AppLogger.debug(f'zmq.stop failed: {e}')

    def quit(self):
        self.stop()
