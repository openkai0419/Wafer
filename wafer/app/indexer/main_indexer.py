from ...utils.paths import data_db_path, setting_db_path
from ...utils.profiling import profiler
from ...utils.logs import AppLogger
from ...core.db.db_utils import remove_orphan_databases, delete_database_files
from ...core.db.setting_db import SettingDB
from ...plugin.collector.handler import collector_resolver
from ...core.ipc.node import Node
from .collector_receiver import CollectorReceiver
from .db_writer import DatabaseWriter
from .dispatcher import CollectorDispatcher
from .progress_notifier import ProgressAggregator
from .scanner import DirectoryScanner
from .scheduler import TaskScheduler, PeriodicTask
from .watch_folder import FolderWatcher
from .watch_setting import SettingWatcher
from .write_command import WriteCommand, WritePriority


class IndexerProcess:

    def __init__(self, name):
        self.db_name = name
        self.setting_db = None
        self.scheduler = None
        self.scanner = None
        self.folder_watcher = None
        self.setting_watcher = None
        self.dispatcher = None
        self.receiver = None
        self.zmq = Node('indexer', db=name, consumer=True)
        self.zmq.subscribe('cleanup', lambda msg: self.cleanup() or True)
        self.zmq.subscribe('rescan', lambda msg: self.rescan() or True)
        self.zmq.start()
        AppLogger.set_node(self.zmq, role='indexer')

    @profiler.profile
    def start_watch(self):
        AppLogger.info(f'indexer start_watch: {self.db_name}')
        self.setting_db = SettingDB(setting_db_path(self.db_name))
        db_path = data_db_path(self.db_name)
        if self.setting_db.get_setting('deleteflag', False) == True:
            self.delete()
            return

        writer = DatabaseWriter(db_path)
        self.scheduler = TaskScheduler(writer)
        self.scheduler.add_periodic_task(PeriodicTask(
            name='truncate_checkpoint',
            interval=60.0,
            create_command=lambda: WriteCommand.create(
                'checkpoint', priority=WritePriority.MAINTENANCE,
                data={'mode': 'TRUNCATE'},
            ),
        ))
        self.scheduler.start()

        collectors = collector_resolver.summary()
        progress = ProgressAggregator(self.db_name, self.zmq)

        self.scanner = DirectoryScanner(db_path, self.scheduler, progress, collectors)
        self.scanner.set_exclude_paths(self.setting_db.get_all_ignore_folders())
        self.scanner.start()
        self.scanner.backfill_pending()

        self.receiver = CollectorReceiver(self.scheduler, progress)
        self.zmq.subscribe('collect.result', self.receiver.handle_result)

        self.dispatcher = CollectorDispatcher(
            self.db_name, db_path, self.scheduler,
        )
        self.dispatcher.start(self.zmq)

        self.folder_watcher = FolderWatcher(self.scheduler, self.scanner, progress)
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
        delete_database_files(data_db_path(self.db_name), force=True)
        remove_orphan_databases()

    def stop(self):
        AppLogger.info(f'indexer stop: {self.db_name}')
        if self.dispatcher:
            self.dispatcher.stop()
        if self.folder_watcher:
            self.folder_watcher.stop()
        if self.scanner:
            self.scanner.stop()
        if self.scheduler:
            self.scheduler.stop()
        if self.setting_watcher:
            self.setting_watcher.stop()
        try:
            self.zmq.stop()
        except Exception as e:
            AppLogger.debug(f'zmq.stop failed: {e}')

