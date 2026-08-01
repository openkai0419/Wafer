import os

from ...utils.paths import data_db_path, setting_db_path
from ...utils.profiling import profiler
from ...utils.logs import AppLogger
from ...core.db.db_utils import remove_orphan_databases, delete_database_files
from ...core.db.setting_db import SettingDB
from ...plugin.collector.handler import collector_resolver
from ...plugin.parser.handler import parser_resolver
from ...core.ipc.node import Node
from ...core.ipc.transport import BROKER_LOST_TIMEOUT
from .receivers.collector_receiver import CollectorReceiver
from .db_writer import DatabaseWriter
from .dispatch.parser_dispatcher import ParserDispatcher
from .receivers.parser_receiver import ParserReceiver
from .dispatch.collector_dispatcher import CollectorDispatcher
from .runtime.progress_aggregator import ProgressAggregator
from .scanner import DirectoryScanner
from .runtime.scheduler import TaskScheduler, PeriodicTask
from .runtime.task import Task, TaskPriority
from .watch.folder_watcher import FolderWatcher
from .watch.setting_watcher import SettingWatcher

_IDLE_GRACE_SECONDS = 60.0


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
        self.zmq = Node("indexer", db=name, consumer=True, broker_lost_timeout=BROKER_LOST_TIMEOUT)
        self.zmq.subscribe("cleanup", lambda msg: self.cleanup() or True)
        self.zmq.subscribe("rescan", lambda msg: self.rescan() or True)
        self.zmq.subscribe("db.delete", lambda msg: self._on_delete_requested() or True)
        self.zmq.subscribe("recollect", self._on_recollect)
        self.zmq.subscribe("keyfilter.reload", self._on_keyfilter_reload)
        self.zmq.subscribe("tags.update", self._on_tags_update)
        self.zmq.subscribe("kv.convert_scope", self._on_kv_convert_scope)
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

        all_parsers = parser_resolver.names()
        if enabled is not None:
            all_known = {c[0] for c in all_collectors} | set(enabled)
            parser_names = [n for n in all_parsers if n in enabled_set or (n not in all_known and getattr(parser_resolver.registry.get(n), "DEFAULT_ENABLED", False))]
        else:
            parser_names = [n for n in all_parsers if n in default_set]

        self.scheduler = TaskScheduler()
        self._register_periodic_tasks(collector_names, parser_names)
        self.scheduler.start()

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

    def _register_periodic_tasks(self, collector_names=(), parser_names=()):
        self.scheduler.set_idle_base_delay(self._child_idle_delay(collector_names, parser_names))

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
                interval=60 * 30 * 1.0,
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

    def _child_idle_delay(self, collector_names, parser_names) -> float:
        timeouts = [collector_resolver.batch_timeout(name) for name in collector_names]
        timeouts.extend(parser_resolver.batch_timeout(name) for name in parser_names)
        if not timeouts:
            return _IDLE_GRACE_SECONDS
        delay = max(timeouts) + _IDLE_GRACE_SECONDS
        AppLogger.info(f"[Indexer] Idle task delay floor: {delay:.1f}s (child batch timeout max={max(timeouts):.1f}s)")
        return delay

    def _request_backfill(self):
        if self.scanner:
            self.scanner.backfill_pending()

    def _request_idle_rescan(self):
        if self.folder_watcher:
            self.folder_watcher.refresh_watch()

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

    def _on_recollect(self, msg):
        payload = msg.payload
        if not isinstance(payload, dict):
            AppLogger.warning(f"recollect: invalid payload: {type(payload)}")
            return True
        if not self.writer or not self.scheduler:
            return True
        mode = payload.get("mode", "reset")
        if mode == "forget":
            self._submit_forget(payload)
        else:
            self._submit_reset(payload)
        return True

    def _submit_reset(self, payload):
        collector = payload.get("collector") or None
        sources = payload.get("sources") or None
        prefixes = payload.get("prefixes") or None
        keys = payload.get("keys") or None
        delete = bool(payload.get("delete", False))
        re_collect = bool(payload.get("re_collect", True))
        if not (keys or delete or re_collect):
            return
        AppLogger.info(f"[Indexer] Recollect reset collector={collector or '*'}, sources={len(sources) if sources else 0}, prefixes={len(prefixes) if prefixes else 0}, keys={len(keys) if keys else 0}, delete={delete}, re_collect={re_collect}")

        def _run():
            return self.writer.reset_collection(collector, sources, prefixes, keys, delete=delete, re_collect=re_collect)

        self.scheduler.submit(
            Task.create(
                "recollect_reset",
                priority=TaskPriority.USER_REQUEST,
                run=_run,
                on_complete=self._recollect_dispatch,
            )
        )

    def _submit_forget(self, payload):
        sources = payload.get("sources") or None
        prefixes = payload.get("prefixes") or None
        scope_all = bool(payload.get("all"))
        AppLogger.info(f"[Indexer] Recollect forget sources={len(sources) if sources else 0}, prefixes={len(prefixes) if prefixes else 0}, all={scope_all}")

        def _run():
            if scope_all:
                self.writer.delete_all_sources()
            elif prefixes:
                self.writer.delete_source_trees(prefixes)
            elif sources:
                self.writer.delete_sources(sources)

        def _after():
            if scope_all:
                self.rescan()
            elif prefixes and self.scanner:
                self.scanner.request_scan(list(prefixes))
            elif sources and self.scanner:
                self.scanner.request_update(list(sources))
            self._progress.send_event("update")

        self.scheduler.submit(
            Task.create(
                "recollect_forget",
                priority=TaskPriority.USER_REQUEST,
                run=_run,
                on_complete=_after,
            )
        )

    def _recollect_dispatch(self):
        self._progress.send_event("update")
        self._request_backfill()

    def _on_keyfilter_reload(self, msg):
        from ...plugin.key_filter import KeyFilter

        KeyFilter.reload()
        AppLogger.info("[Indexer] Key filter reloaded")
        return True

    def _on_tags_update(self, msg):
        payload = msg.payload
        if not isinstance(payload, dict):
            AppLogger.warning(f"tags.update: invalid payload: {type(payload)}")
            return True
        paths = payload.get("paths", []) or []
        upserts_raw = payload.get("upserts", []) or []
        renames_raw = payload.get("renames", []) or []
        deletes_raw = payload.get("deletes", []) or []
        request_id = payload.get("request_id", "")
        lock_only = bool(payload.get("lock_only", False))
        scope = str(payload.get("scope") or "tag")
        if scope not in ("tag", "meta_info", "*"):
            AppLogger.warning(f"tags.update: unsupported scope: {scope}")
            return True
        if scope == "*" and (upserts_raw or renames_raw or lock_only):
            AppLogger.warning("tags.update: scope=* only supports deletes")
            return True
        if not self.writer or not self.scheduler or not paths:
            return True

        def _coerce_value(value):
            value_str = "" if value is None else str(value)
            try:
                value_num = float(value_str)
            except (TypeError, ValueError):
                value_num = None
            return value_str, value_num

        upserts: list[tuple[str, str, float | None, int]] = []
        for item in upserts_raw:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or "").strip()
            if not key:
                continue
            value_str, value_num = _coerce_value(item.get("value"))
            locked = 1 if item.get("locked") else 0
            upserts.append((key, value_str, value_num, locked))
        renames: list[tuple[str, str, str, float | None, int]] = []
        for item in renames_raw:
            if not isinstance(item, dict):
                continue
            old_key = str(item.get("old") or "").strip()
            new_key = str(item.get("new") or "").strip()
            if not old_key or not new_key:
                continue
            value_str, value_num = _coerce_value(item.get("value"))
            locked = 1 if item.get("locked") else 0
            renames.append((old_key, new_key, value_str, value_num, locked))
        deletes = [k for k in (str(d).strip() for d in deletes_raw) if k]

        result: dict = {}

        def _run():
            result["data"] = self.writer.apply_user_kv(
                list(paths),
                upserts,
                list(deletes),
                scope=scope,
                lock_only=lock_only,
                renames=renames,
            )

        def _on_done():
            data: dict = result.get("data") or {}
            applied_by_path = {p: list(applied) for p, (_fh, applied, _del) in data.items()}
            deleted_by_path = {p: list(deleted) for p, (_fh, _ap, deleted) in data.items()}
            targets_by_path = {p: target for p, (target, _ap, _del) in data.items()}
            hashes_by_path = targets_by_path if scope in ("tag", "*") else {}
            self.zmq.send(
                "tags.updated",
                {
                    "paths": list(paths),
                    "scope": scope,
                    "applied": applied_by_path,
                    "deleted": deleted_by_path,
                    "file_hashes": hashes_by_path,
                    "targets": targets_by_path,
                    "request_id": request_id,
                    "db": self.db_name,
                },
                dst="viewer",
            )
            self._progress.send_event("update")

        self.scheduler.submit(
            Task.create(
                "apply_user_kv",
                priority=TaskPriority.USER_REQUEST,
                run=_run,
                on_complete=_on_done,
            )
        )
        return True

    def _on_kv_convert_scope(self, msg):
        payload = msg.payload
        if not isinstance(payload, dict):
            AppLogger.warning(f"kv.convert_scope: invalid payload: {type(payload)}")
            return True
        key = str(payload.get("key") or "").strip()
        to_scope = str(payload.get("to_scope") or "").strip()
        request_id = str(payload.get("request_id") or "")
        if not key or to_scope not in ("tag", "meta_info"):
            AppLogger.warning(f"kv.convert_scope: invalid key/scope key={key!r} to_scope={to_scope!r}")
            return True
        if not self.writer or not self.scheduler:
            return True

        result: dict = {}

        def _run():
            result["data"] = self.writer.convert_key_scope(key, to_scope)

        def _on_done():
            data = dict(result.get("data") or {})
            self.zmq.send(
                "tags.updated",
                {
                    "paths": list(data.get("paths") or []),
                    "scope": "*",
                    "applied": {},
                    "deleted": {},
                    "targets": dict(data.get("targets") or {}),
                    "request_id": request_id,
                    "db": self.db_name,
                    "key": data.get("key", key),
                    "from_scope": data.get("from_scope"),
                    "to_scope": data.get("to_scope", to_scope),
                    "upserted": int(data.get("upserted") or 0),
                    "source_deleted": int(data.get("source_deleted") or 0),
                },
                dst="viewer",
            )
            if self._progress is not None:
                self._progress.send_event("update")

        self.scheduler.submit(
            Task.create(
                "convert_key_scope",
                priority=TaskPriority.USER_REQUEST,
                run=_run,
                on_complete=_on_done,
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
