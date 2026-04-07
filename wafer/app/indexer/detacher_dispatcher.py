from __future__ import annotations

import os
import threading
from pathlib import Path

from ...core.db.db_utils import apply_read_pragmas, connect_with_retry
from ...utils.logs import AppLogger
from ...utils.profiling import profiler
from ...core.platform.process import AppProcess
from ...plugin.detacher.handler import detacher_resolver
from .db_writer import DatabaseWriter
from .progress_notifier import ProgressAggregator
from .scheduler import TaskScheduler
from .task import Task, TaskPriority

_DISPATCH_INTERVAL = 2.0


class DetacherDispatcher:
    _singleton_started: set[str] = set()
    _singleton_lock = threading.Lock()

    def __init__(
        self,
        db_name: str,
        db_path: str | Path,
        scheduler: TaskScheduler,
        writer: DatabaseWriter,
        progress: ProgressAggregator,
        detachers=None,
    ):
        self._db_name = db_name
        self._db_path = Path(db_path)
        self._scheduler = scheduler
        self._writer = writer
        self._progress = progress
        self._detachers = list(detachers or detacher_resolver.names())
        self._per_indexer = [d for d in self._detachers if d not in detacher_resolver.singleton_names()]
        self._dispatched_paths: dict[str, set[str]] = {}
        self._dispatched_lock = threading.Lock()
        self._read_conn = None
        self._node = None
        self._stop = threading.Event()
        self._dispatch_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, node):
        self._node = node
        uri = self._db_path.resolve().as_uri()
        self._read_conn = connect_with_retry(
            f"{uri}?mode=ro",
            timeout=1.0,
            uri=True,
            check_same_thread=False,
        )
        apply_read_pragmas(self._read_conn)
        self._reset_stale()
        self._start_detacher_processes()
        self._thread = threading.Thread(target=self._dispatch_loop, daemon=True)
        self._thread.start()

    def _reset_stale(self):
        status_names = [detacher_resolver.status_name(d) for d in self._detachers]
        self._scheduler.submit(
            Task.create(
                "reset_stale_detacher",
                priority=TaskPriority.DISPATCH,
                run=lambda: self._writer.reset_stale(status_names),
            )
        )

    def stop(self):
        self._stop.set()
        self._dispatch_event.set()
        self._terminate_detachers()
        if self._thread:
            self._thread.join(timeout=5.0)
        if self._read_conn:
            self._read_conn.close()
            self._read_conn = None

    def request_dispatch(self):
        self._dispatch_event.set()

    def _start_detacher_processes(self):
        my_pid = str(os.getpid())
        for plugin in self._per_indexer:
            AppProcess.new_main(
                "--detacher",
                self._db_name,
                "--plugin",
                plugin,
                "--parent-pid",
                my_pid,
            )
        singletons_launched = []
        with DetacherDispatcher._singleton_lock:
            for plugin in self._detachers:
                if plugin in self._per_indexer:
                    continue
                if plugin not in DetacherDispatcher._singleton_started:
                    AppProcess.new_main(
                        "--detacher",
                        self._db_name,
                        "--plugin",
                        plugin,
                        "--parent-pid",
                        my_pid,
                    )
                    DetacherDispatcher._singleton_started.add(plugin)
                    singletons_launched.append(plugin)
        started = self._per_indexer + singletons_launched
        if started:
            AppLogger.info(f"[DetacherDispatcher] Started detachers: {started}")

    def _terminate_detachers(self):
        for plugin in self._per_indexer:
            AppProcess.terminate_cmd("--detacher", self._db_name, "--plugin", plugin)
        AppLogger.info(f"[DetacherDispatcher] Terminated per-indexer detachers for db={self._db_name}")

    def _dispatch_loop(self):
        while not self._stop.is_set():
            self._dispatch_event.wait(timeout=_DISPATCH_INTERVAL)
            self._dispatch_event.clear()
            if self._stop.is_set():
                break
            try:
                self._dispatch_pending()
            except Exception as e:
                AppLogger.error(f"[DetacherDispatcher] _dispatch_pending failed: {e}", exc=e)

    @profiler.profile
    def _dispatch_pending(self):
        for detacher_name in self._detachers:
            status_name = detacher_resolver.status_name(detacher_name)
            batch_size = detacher_resolver.batch_size(detacher_name)
            trigger_keys = detacher_resolver.trigger_keys(detacher_name)
            cur = self._read_conn.cursor()
            cur.execute(
                """SELECT cs.source, s.modified, s.size, s.file_hash
                FROM collection_status cs
                JOIN sources s ON s.source = cs.source
                WHERE cs.collector = ? AND cs.status = 'pending'
                LIMIT ?""",
                (status_name, batch_size),
            )
            pending = cur.fetchall()
            cur.close()
            if not pending:
                continue
            with self._dispatched_lock:
                already = self._dispatched_paths.get(detacher_name, set())
                rows = [row for row in pending if row[0] not in already]
            if not rows:
                continue
            paths = [row[0] for row in rows]
            file_info = {row[0]: (row[1], row[2], row[3]) for row in rows}
            metadata = self._writer.db.get_trigger_metadata(paths, trigger_keys) if trigger_keys else {}
            with self._dispatched_lock:
                self._dispatched_paths.setdefault(detacher_name, set()).update(paths)
            self._scheduler.submit(
                Task.create(
                    "mark_dispatched_detacher",
                    priority=TaskPriority.DISPATCH,
                    run=lambda ps=paths, sn=status_name: self._writer.mark_dispatched(ps, sn),
                    on_complete=lambda dn=detacher_name, ps=paths: self._clear_dispatched(dn, ps),
                )
            )
            self._progress.increment(0, len(paths))
            self._node.send(
                "detach.batch",
                {"paths": paths, "file_info": file_info, "metadata": metadata},
                dst=f"detacher-{detacher_name}",
                db=self._db_name,
            )
            AppLogger.info(f"[DetacherDispatcher] Sent {len(paths)} paths to detacher-{detacher_name}")

    def _clear_dispatched(self, detacher_name: str, paths: list[str]):
        with self._dispatched_lock:
            s = self._dispatched_paths.get(detacher_name)
            if s:
                s.difference_update(paths)
