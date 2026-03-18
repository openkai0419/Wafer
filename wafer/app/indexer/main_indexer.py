import os

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
from .task import Task, TaskPriority
from .watch_folder import FolderWatcher
from .watch_setting import SettingWatcher


class IndexerProcess:

    def __init__(self, name, stop_event=None):
        self.db_name = name
        self._stop_event = stop_event
        self.setting_db = None
        self.scheduler = None
        self.writer = None
        self.scanner = None
        self.folder_watcher = None
        self.setting_watcher = None
        self.dispatcher = None
        self.receiver = None
        self.zmq = Node('indexer', db=name, consumer=True)
        self.zmq.subscribe('cleanup', lambda msg: self.cleanup() or True)
        self.zmq.subscribe('rescan', lambda msg: self.rescan() or True)
        self.zmq.subscribe('db.delete', lambda msg: self._on_delete_requested() or True)
        self.zmq.start()
        AppLogger.set_node(self.zmq, role='indexer')

    @profiler.profile
    def start_watch(self):
        AppLogger.info(f'indexer start_watch: {self.db_name}')
        self.setting_db = SettingDB(setting_db_path(self.db_name))
        db_path = data_db_path(self.db_name)
        is_new = not os.path.exists(db_path)

        self.writer = DatabaseWriter(db_path)
        self.writer.start()
        self.writer.initialize()

        self.scheduler = TaskScheduler()
        self._register_periodic_tasks()
        self.scheduler.start()

        collectors = collector_resolver.summary()
        progress = ProgressAggregator(self.db_name, self.zmq)

        self.scanner = DirectoryScanner(db_path, self.scheduler, self.writer, progress, collectors)
        self.scanner.set_exclude_paths(self.setting_db.get_all_ignore_folders())
        self.scanner.start()
        self.scanner.backfill_pending()

        self.receiver = CollectorReceiver(self.scheduler, self.writer, progress)
        self.zmq.subscribe('collect.result', self.receiver.handle_result)

        self.dispatcher = CollectorDispatcher(
            self.db_name, db_path, self.scheduler, self.writer,
        )
        self.dispatcher.start(self.zmq)

        self.folder_watcher = FolderWatcher(self.scheduler, self.writer, self.scanner, progress)
        self.folder_watcher.start(self.setting_db.get_all_parent_folders())
        self.setting_watcher = SettingWatcher(self.setting_db)
        self.setting_watcher.parent_folders_changed.connect(self.folder_watcher.start)
        self.setting_watcher.ignore_folders_changed.connect(self.folder_watcher.set_ignore_paths)
        self.setting_watcher.start()

        if is_new:
            self.zmq.send('db.created', self.db_name, dst='viewer')

    def _register_periodic_tasks(self):
        self.scheduler.add_periodic_task(PeriodicTask(
            name='truncate_checkpoint',
            interval=60*1.0,
            create_task=lambda: Task.create(
                'checkpoint',
                priority=TaskPriority.MAINTENANCE,
                run=lambda: self.writer.checkpoint('TRUNCATE'),
            ),
        ))
        self.scheduler.add_periodic_task(PeriodicTask(
            name='retry_stale_dispatched',
            interval=60*5.0,
            idle_delay=60*1.0,
            create_task=lambda: Task.create(
                'reset_stale',
                priority=TaskPriority.RETRY,
                run=lambda: self.writer.reset_stale(),
            ),
        ))
        self.scheduler.add_periodic_task(PeriodicTask(
            name='idle_rescan',
            interval=60*60*1.0,
            idle_delay=60*5.0,
            create_task=lambda: Task.create(
                'idle_rescan',
                priority=TaskPriority.MAINTENANCE,
                run=lambda: self._request_idle_rescan(),
            ),
        ))
        self.scheduler.add_periodic_task(PeriodicTask(
            name='cleanup_optimize',
            interval=60*60*12.0,
            idle_delay=60*30.0,
            create_task=lambda: Task.create(
                'cleanup_optimize',
                priority=TaskPriority.MAINTENANCE,
                run=lambda: self.writer.purge_orphans(),
            ),
        ))

    def _request_idle_rescan(self):
        if self.folder_watcher:
            self.folder_watcher.rescan_all()

    def rescan(self):
        if self.folder_watcher:
            self.folder_watcher.rescan_all()

    def cleanup(self):
        if self.folder_watcher:
            self.folder_watcher.request_cleanup()

    def _on_delete_requested(self):
        AppLogger.info(f'indexer delete requested via IPC: {self.db_name}')
        if not self.scheduler:
            self.delete()
            return
        self.scheduler.cancel_all()
        self.scheduler.submit(Task.create(
            'db_delete',
            priority=TaskPriority.SHUTDOWN,
            run=self.delete,
        ))

    def delete(self):
        AppLogger.info(f'indexer delete: {self.db_name}')
        self._stop_components()
        if self.setting_db:
            delete_database_files(self.setting_db.db_name, force=True)
        delete_database_files(data_db_path(self.db_name), force=True)
        remove_orphan_databases()
        self.zmq.send('db.deleted', self.db_name, dst='viewer')
        self._stop_zmq()
        if self._stop_event:
            self._stop_event.set()

    def stop(self):
        AppLogger.info(f'indexer stop: {self.db_name}')
        self._stop_components()
        self._stop_zmq()

    def _stop_components(self):
        if self.dispatcher:
            self.dispatcher.stop()
        if self.folder_watcher:
            self.folder_watcher.stop()
        if self.scanner:
            self.scanner.stop()
        if self.scheduler:
            self.scheduler.stop()
        if self.writer:
            self.writer.close()
        if self.setting_watcher:
            self.setting_watcher.stop()

    def _stop_zmq(self):
        try:
            self.zmq.stop()
        except Exception as e:
            AppLogger.debug(f'zmq.stop failed: {e}')

