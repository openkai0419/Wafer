from __future__ import annotations

import os
import threading
from pathlib import Path

from ....core.db.db_utils import open_readonly
from ....core.logs import AppLogger
from ....core.profiling import profiler
from ....core.platform.process import AppProcess
from ....plugin.collector.handler import collector_resolver
from ..db_writer import DatabaseWriter
from ..runtime.progress_aggregator import ProgressAggregator
from ..runtime.scheduler import TaskScheduler
from ..runtime.worker_shutdown import WORKER_SHUTDOWN_TIMEOUT, wait_worker_stopped

_DISPATCH_INTERVAL = 2.0


class CollectorDispatcher:
    _singleton_started: set[str] = set()
    _singleton_lock = threading.Lock()

    @classmethod
    def reset_singleton_state(cls):
        with cls._singleton_lock:
            cls._singleton_started.clear()

    def __init__(
        self,
        db_name: str,
        db_path: str | Path,
        scheduler: TaskScheduler,
        writer: DatabaseWriter,
        progress: ProgressAggregator,
        collectors=None,
        tray_pid=None,
    ):
        self._db_name = db_name
        self._db_path = Path(db_path)
        self._scheduler = scheduler
        self._writer = writer
        self._progress = progress
        self._collectors = list(collectors or collector_resolver.names())
        self._per_indexer = [c for c in self._collectors if c not in collector_resolver.singleton_names()]
        self._tray_pid = tray_pid
        self._read_conn = None
        self._node = None
        self._stop = threading.Event()
        self._dispatch_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, node):
        self._node = node
        self._read_conn = open_readonly(self._db_path)
        self._start_collector_processes()
        self._thread = threading.Thread(target=self._dispatch_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._dispatch_event.set()
        self._terminate_collectors()
        if self._thread:
            self._thread.join(timeout=5.0)
        if self._read_conn:
            self._read_conn.close()
            self._read_conn = None

    def request_dispatch(self):
        self._dispatch_event.set()

    def _start_collector_processes(self):
        my_pid = str(os.getpid())
        singleton_parent = str(self._tray_pid) if self._tray_pid else my_pid
        for plugin in self._per_indexer:
            AppProcess.new_main(
                "--collector",
                self._db_name,
                "--plugin",
                plugin,
                "--parent-pid",
                my_pid,
            )
        singletons_launched = []
        with CollectorDispatcher._singleton_lock:
            for plugin in self._collectors:
                if plugin in self._per_indexer:
                    continue
                if plugin not in CollectorDispatcher._singleton_started:
                    AppProcess.new_main(
                        "--collector",
                        self._db_name,
                        "--plugin",
                        plugin,
                        "--parent-pid",
                        singleton_parent,
                    )
                    CollectorDispatcher._singleton_started.add(plugin)
                    singletons_launched.append(plugin)
        started = self._per_indexer + singletons_launched
        AppLogger.info(f"[Dispatcher] Started collectors: {started}")

    def _terminate_collectors(self):
        for plugin in self._per_indexer:
            self._request_collector_shutdown(plugin)
        for plugin in self._per_indexer:
            if not self._wait_collector_stopped(plugin, WORKER_SHUTDOWN_TIMEOUT):
                AppProcess.terminate_cmd("--collector", self._db_name, "--plugin", plugin, recursive=True)
        AppLogger.info(f"[Dispatcher] Terminated per-indexer collectors for db={self._db_name}")

    def _request_collector_shutdown(self, plugin: str):
        if self._node is None:
            return
        self._node.send(
            "worker.shutdown",
            {"plugin": plugin},
            dst=f"collector-{plugin}",
            db=self._db_name,
        )

    def _wait_collector_stopped(self, plugin: str, timeout: float) -> bool:
        return wait_worker_stopped("collector", self._db_name, plugin, timeout)

    def _dispatch_loop(self):
        try:
            self._writer.reset_stale(self._collectors)
        except Exception as e:
            AppLogger.error(f"[Dispatcher] reset_stale failed: {e}", exc=e)
        while not self._stop.is_set():
            self._dispatch_event.wait(timeout=_DISPATCH_INTERVAL)
            self._dispatch_event.clear()
            if self._stop.is_set():
                break
            try:
                self._dispatch_pending()
            except Exception as e:
                AppLogger.error(f"[Dispatcher] _dispatch_pending failed: {e}", exc=e)

    @profiler.profile
    def _dispatch_pending(self):
        for collector in self._collectors:
            dst = f"collector-{collector}"
            if self._node.nudge_undelivered("collect.batch", dst=dst, db=self._db_name):
                continue
            batch_size = collector_resolver.batch_size(collector)
            cur = self._read_conn.cursor()
            cur.execute(
                """SELECT cs.source, s.modified, s.size, s.file_hash
                FROM collection_status cs
                JOIN sources s ON s.source = cs.source
                WHERE cs.collector = ? AND cs.status = 'pending'
                LIMIT ?""",
                (collector, batch_size),
            )
            rows = cur.fetchall()
            cur.close()
            if not rows:
                continue
            paths = [row[0] for row in rows]
            file_info = {row[0]: (row[1], row[2], row[3]) for row in rows}
            # Before the batch leaves, not through the scheduler: a mark that runs later would
            # turn a source set pending again meanwhile into 'dispatched' with no batch behind it.
            self._writer.mark_dispatched(paths, collector)
            try:
                self._node.send_reliable(
                    "collect.batch",
                    {"paths": paths, "file_info": file_info},
                    dst=dst,
                    db=self._db_name,
                )
            except Exception:
                self._writer.unmark_dispatched(paths, collector)
                raise
            self._scheduler.note_activity()
            self._progress.increment(0, len(paths))
            AppLogger.info(f"[Dispatcher] Sent {len(paths)} paths to {dst}")
