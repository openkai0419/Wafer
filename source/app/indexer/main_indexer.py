from source.utils.paths import data_db_path, setting_db_path
from source.utils.profiling import profiler
from source.utils.logs import AppLogger
from source.core.db.indexer import FileIndexer
from source.core.db.db_utils import remove_orphan_databases, delete_database_files
from source.core.db.setting_db import SettingDB
from source.plugin_core.collector.handler import collector_resolver
from source.core.zmq.node import Node
from .dispatcher import CollectorDispatcher
from .progress_notifier import ProgressAggregator
from .watch_folder import FolderWatcher
from .watch_setting import SettingWatcher
from .writer import CollectionWriter


class IndexerProcess:

    def __init__(self, name):
        self.db_name = name
        self.setting_db = None
        self.indexer = None
        self.folder_watcher = None
        self.setting_watcher = None
        self.dispatcher = None
        self.writer = None
        self.zmq = Node('indexer', db=name, consumer=True)
        self.zmq.subscribe('cleanup', lambda msg: self.cleanup() or True)
        self.zmq.subscribe('rescan', lambda msg: self.rescan() or True)
        self.zmq.start()
        AppLogger.set_node(self.zmq, role='indexer')

    @profiler.profile
    def start_watch(self):
        AppLogger.info(f'indexer start_watch: {self.db_name}')
        self.setting_db = SettingDB(setting_db_path(self.db_name))
        self.indexer = FileIndexer(data_db_path(self.db_name), collectors=collector_resolver.summary())
        self.indexer.set_exclude_paths(self.setting_db.get_all_ignore_folders())
        if self.setting_db.get_setting('deleteflag', False) == True:
            self.delete()
            return
        with self.indexer as idx:
            idx.initialize()
            idx.backfill_pending_for_collectors()

        progress = ProgressAggregator(self.db_name, self.zmq)

        self.writer = CollectionWriter(data_db_path(self.db_name), progress)
        self.zmq.subscribe('collect.result', self.writer.handle_result)
        self.writer.start()

        self.dispatcher = CollectorDispatcher(self.db_name, self.indexer)
        self.dispatcher.start(self.zmq)

        self.folder_watcher = FolderWatcher(self.indexer, progress)
        self.folder_watcher.start(self.setting_db.get_all_parent_folders())
        self.setting_watcher = SettingWatcher(self.setting_db)
        self.setting_watcher.parent_folders_changed.connect(self.folder_watcher.start)
        self.setting_watcher.ignore_folders_changed.connect(self.folder_watcher.set_ignore_paths)
        self.setting_watcher.delete_requested.connect(self.delete)
        self.setting_watcher.start()

    def rescan(self):
        if self.folder_watcher:
            self.folder_watcher.rescan_all()

    def cleanup(self):
        if self.folder_watcher:
            self.folder_watcher.request_cleanup()

    def delete(self):
        AppLogger.info(f'indexer delete: {self.db_name}')
        self.stop()
        delete_database_files(self.setting_db.db_name, force=True)
        delete_database_files(self.indexer.db_path, force=True)
        remove_orphan_databases()

    def stop(self):
        AppLogger.info(f'indexer stop: {self.db_name}')
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

