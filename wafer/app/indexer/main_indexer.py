import os

from ...utils.paths import data_db_path, setting_db_path
from ...utils.profiling import profiler
from ...utils.logs import AppLogger
from ...core.db.db_utils import remove_orphan_databases, delete_database_files
from ...core.db.setting_db import SettingDB
from ...plugin.collector.handler import collector_resolver
from ...plugin.parser.handler import parser_resolver
from ...core.ipc.node import Node
from .collector_receiver import CollectorReceiver
from .db_writer import DatabaseWriter
from .parser_dispatcher import ParserDispatcher
from .parser_receiver import ParserReceiver
from .dispatcher import CollectorDispatcher
from .progress_notifier import ProgressAggregator
from .scanner import DirectoryScanner
from .scheduler import TaskScheduler, PeriodicTask
from .task import Task, TaskPriority
from .watch_folder import FolderWatcher
from .watch_setting import SettingWatcher


class IndexerProcess:
    def __init__(self, name, stop_event=None, tray_pid=None):
        self.db_name = name
        self._stop_event = stop_event
        self._tray_pid = tray_pid
        self.setting_db = None
        self.scheduler = None
        self.writer = None
        self.scanner = None
        self.folder_watcher = None
        self.setting_watcher = None
        self.dispatcher = None
        self.receiver = None
        self.parser_dispatcher = None
        self.parser_receiver = None
        self._progress = None
        self.zmq = Node("indexer", db=name, consumer=True)
        self.zmq.subscribe("cleanup", lambda msg: self.cleanup() or True)
        self.zmq.subscribe("rescan", lambda msg: self.rescan() or True)
        self.zmq.subscribe("db.delete", lambda msg: self._on_delete_requested() or True)
        self.zmq.subscribe("delete.collector", self._on_delete_collector)
        self.zmq.subscribe("delete.keys", self._on_delete_keys)
        self.zmq.start()
        AppLogger.set_node(self.zmq, role="indexer")

    @profiler.profile
    def start_watch(self):
        AppLogger.info(f"indexer start_watch: {self.db_name}")
        self.setting_db = SettingDB(setting_db_path(self.db_name))
        db_path = data_db_path(self.db_name)
        is_new = not os.path.exists(db_path)

        self.writer = DatabaseWriter(db_path)
        self.writer.start()
        self.writer.initialize()

        self.scheduler = TaskScheduler()
        self._register_periodic_tasks()
        self.scheduler.start()

        all_collectors = collector_resolver.summary()
        enabled = self.setting_db.get_enabled_collectors()
        if enabled is not None:
            enabled_set = set(enabled)
            collectors = [(n, exts) for n, exts in all_collectors if n in enabled_set]
            collector_names = [n for n in enabled if n in {c[0] for c in all_collectors}]
        else:
            from ...plugin.settings import PluginSettings
            default_set = set(PluginSettings().resolve_default_collectors())
            collectors = [(n, exts) for n, exts in all_collectors if n in default_set]
            collector_names = [n for n, _ in collectors]
        progress = ProgressAggregator(self.db_name, self.zmq)
        self._progress = progress

        self.scanner = DirectoryScanner(db_path, self.scheduler, self.writer, progress, collectors)
        self.scanner.set_exclude_paths(self.setting_db.get_all_ignore_folders())
        self.scanner.start()

        self.receiver = CollectorReceiver(self.scheduler, self.writer, progress)
        self.zmq.subscribe("collect.result", self.receiver.handle_result)

        self.dispatcher = CollectorDispatcher(
            self.db_name,
            db_path,
            self.scheduler,
            self.writer,
            progress,
            collectors=collector_names,
            tray_pid=self._tray_pid,
        )
        self.dispatcher.start(self.zmq)

        all_parsers = parser_resolver.names()
        if enabled is not None:
            all_known = {c[0] for c in all_collectors} | set(enabled)
            parser_names = [n for n in all_parsers if n in enabled_set or (n not in all_known and getattr(parser_resolver.registry.get(n), "DEFAULT_ENABLED", False))]
        else:
            parser_names = [n for n in all_parsers if n in default_set]
        if parser_names:
            self.parser_receiver = ParserReceiver(self.scheduler, self.writer, progress)
            self.zmq.subscribe("parse.result", self.parser_receiver.handle_result)
            self.parser_dispatcher = ParserDispatcher(
                self.db_name,
                db_path,
                self.scheduler,
                self.writer,
                progress,
                parsers=parser_names,
                tray_pid=self._tray_pid,
            )
            self.parser_dispatcher.start(self.zmq)
            self.parser_receiver.set_request_dispatch(self.parser_dispatcher.request_dispatch)
            self.receiver.set_parser_dispatch(
                self.parser_dispatcher.request_dispatch,
                self.writer,
            )
            self.scanner.set_parsers([(parser_resolver.status_name(n), parser_resolver.trigger_keys(n)) for n in parser_names])

        self.scanner.backfill_pending()

        self.folder_watcher = FolderWatcher(self.scheduler, self.writer, self.scanner, progress)
        self.folder_watcher.start(self.setting_db.get_all_parent_folders())
        self.setting_watcher = SettingWatcher(self.setting_db)
        self.setting_watcher.parent_folders_changed.connect(self.folder_watcher.start)
        self.setting_watcher.ignore_folders_changed.connect(self.folder_watcher.set_ignore_paths)
        self.setting_watcher.parent_folders_changed.connect(lambda _: progress.send_event("folderchanged"))
        self.setting_watcher.ignore_folders_changed.connect(lambda _: progress.send_event("folderchanged"))
        self.setting_watcher.start()

        if is_new:
            self.zmq.send("db.created", self.db_name, dst="viewer")

    def _register_periodic_tasks(self):
        self.scheduler.add_periodic_task(
            PeriodicTask(
                name="truncate_checkpoint",
                interval=10.0,
                once_per_idle=True,
                create_task=lambda: Task.create(
                    "checkpoint",
                    priority=TaskPriority.MAINTENANCE,
                    run=lambda: self.writer.checkpoint("TRUNCATE"),
                ),
            )
        )
        self.scheduler.add_periodic_task(
            PeriodicTask(
                name="retry_stale_dispatched",
                interval=60 * 5.0,
                idle_delay=60 * 1.0,
                create_task=lambda: Task.create(
                    "reset_stale",
                    priority=TaskPriority.RETRY,
                    run=lambda: self.writer.reset_stale(),
                ),
            )
        )
        self.scheduler.add_periodic_task(
            PeriodicTask(
                name="backfill_pending",
                interval=60 * 10.0,
                idle_delay=60 * 2.0,
                create_task=lambda: Task.create(
                    "backfill_pending",
                    priority=TaskPriority.RETRY,
                    run=lambda: self._request_backfill(),
                ),
            )
        )
        self.scheduler.add_periodic_task(
            PeriodicTask(
                name="idle_rescan",
                interval=60 * 60 * 1.0,
                idle_delay=60 * 5.0,
                create_task=lambda: Task.create(
                    "idle_rescan",
                    priority=TaskPriority.RETRY,
                    run=lambda: self._request_idle_rescan(),
                ),
            )
        )
        self.scheduler.add_periodic_task(
            PeriodicTask(
                name="cleanup_optimize",
                interval=60 * 60 * 12.0,
                idle_delay=60 * 30.0,
                once_per_idle=True,
                create_task=lambda: Task.create(
                    "cleanup_optimize",
                    priority=TaskPriority.MAINTENANCE,
                    run=lambda: self.writer.delete_orphans(),
                ),
            )
        )
        self.scheduler.add_periodic_task(
            PeriodicTask(
                name="idle_progress_reset",
                interval=60 * 1.0,
                idle_delay=30.0,
                once_per_idle=True,
                create_task=lambda: Task.create(
                    "progress_reset",
                    priority=TaskPriority.MAINTENANCE,
                    run=lambda: self._progress.reset() if self._progress and self._progress.maximum > 0 else None,
                ),
            )
        )

    def _request_backfill(self):
        if self.scanner:
            self.scanner.backfill_pending()

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
        AppLogger.info(f"indexer delete requested via IPC: {self.db_name}")
        if not self.scheduler:
            self.delete()
            return
        self.scheduler.cancel_all()
        self.scheduler.submit(
            Task.create(
                "db_delete",
                priority=TaskPriority.SHUTDOWN,
                run=self.delete,
            )
        )

    def _on_delete_collector(self, msg):
        payload = msg.payload
        if not isinstance(payload, dict):
            AppLogger.warning(f"delete.collector: invalid payload: {type(payload)}")
            return True
        collector = payload.get("collector", "")
        re_collect = payload.get("re_collect", False)
        if not collector or not self.writer:
            return True
        AppLogger.info(f"[Indexer] Delete collector={collector}, re_collect={re_collect}")

        self.scheduler.submit(
            Task.create(
                "delete_collector_data",
                priority=TaskPriority.USER_REQUEST,
                run=lambda: self.writer.delete_collector(collector, re_collect=re_collect),
                on_complete=lambda: self.zmq.send(
                    "delete.complete",
                    {"collector": collector, "db": self.db_name},
                    dst="viewer",
                ),
            )
        )
        return True

    def _on_delete_keys(self, msg):
        payload = msg.payload
        if not isinstance(payload, dict):
            AppLogger.warning(f"delete.keys: invalid payload: {type(payload)}")
            return True
        keys = payload.get("keys", [])
        re_collect = payload.get("re_collect", False)
        collector = payload.get("collector", "")
        if not self.writer:
            return True
        if not keys and not (re_collect and collector):
            return True
        AppLogger.info(f"[Indexer] Delete keys={len(keys)}, collector={collector}, re_collect={re_collect}")

        def _run():
            if keys:
                self.writer.delete_keys(keys)
            if re_collect and collector:
                self.writer.reset_collector_status(collector)

        self.scheduler.submit(
            Task.create(
                "delete_keys",
                priority=TaskPriority.USER_REQUEST,
                run=_run,
                on_complete=lambda: self.zmq.send(
                    "delete.complete",
                    {"collector": collector, "keys": keys, "db": self.db_name},
                    dst="viewer",
                ),
            )
        )
        return True

    def delete(self):
        AppLogger.info(f"indexer delete: {self.db_name}")
        self._stop_components()
        if self.setting_db:
            delete_database_files(self.setting_db.db_name, force=True)
        delete_database_files(data_db_path(self.db_name), force=True)
        remove_orphan_databases()
        self.zmq.send("db.deleted", self.db_name, dst="viewer")
        self._stop_zmq()
        if self._stop_event:
            self._stop_event.set()

    def stop(self):
        AppLogger.info(f"indexer stop: {self.db_name}")
        self._stop_components()
        self._stop_zmq()

    def _stop_components(self):
        if self.parser_dispatcher:
            self.parser_dispatcher.stop()
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
            AppLogger.debug(f"zmq.stop failed: {e}")
