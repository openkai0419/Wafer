from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path

from ....core.db.db_utils import open_readonly
from ....core.db.file_db import read_pending_sources
from ....core.logs import AppLogger
from ....core.profiling import profiler
from ....core.platform.process import AppProcess
from ..db_writer import DatabaseWriter
from ..runtime.progress_aggregator import ProgressAggregator
from ..runtime.scheduler import TaskScheduler
from ..runtime.worker_shutdown import WORKER_SHUTDOWN_TIMEOUT, wait_workers_stopped

_DISPATCH_INTERVAL = 2.0
MAX_IN_FLIGHT_BATCHES = 4
BATCH_GRACE_SECONDS = 60.0


class PluginDispatcher:
    KIND = ""
    BATCH_TOPIC = ""
    resolver = None

    def __init__(
        self,
        db_name: str,
        db_path: str | Path,
        scheduler: TaskScheduler,
        writer: DatabaseWriter,
        progress: ProgressAggregator,
        plugins=None,
        tray_pid=None,
    ):
        self._db_name = db_name
        self._db_path = Path(db_path)
        self._scheduler = scheduler
        self._writer = writer
        self._progress = progress
        self._plugins = list(plugins or self.resolver.names())
        singletons = set(self.resolver.singleton_names())
        self._per_indexer = [p for p in self._plugins if p not in singletons]
        self._tray_pid = tray_pid
        self._read_conn = None
        self._node = None
        self._stop = threading.Event()
        self._dispatch_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._worker_procs: dict[str, subprocess.Popen] = {}
        self._in_flight: dict[str, int] = {}
        self._last_sent: dict[str, float] = {}
        self._paused: dict[str, set[str]] = {}
        self._retried: dict[str, set[str]] = {}
        self._in_flight_lock = threading.Lock()
        self._tag = f"[{type(self).__name__}]"

    def start(self, node):
        self._node = node
        self._read_conn = open_readonly(self._db_path)
        self._start_workers()
        self._thread = threading.Thread(target=self._dispatch_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._dispatch_event.set()
        self._terminate_workers()
        if self._thread:
            self._thread.join(timeout=5.0)
        if self._read_conn:
            self._read_conn.close()
            self._read_conn = None

    def request_dispatch(self):
        self._dispatch_event.set()

    def status_name(self, plugin: str) -> str:
        return plugin

    def batch_done(self, status_name: str, paused=()):
        with self._in_flight_lock:
            self._in_flight[status_name] = max(0, self._in_flight.get(status_name, 0) - 1)
            if paused:
                self._paused.setdefault(status_name, set()).update(paused)

    def resume_paused(self):
        with self._in_flight_lock:
            self._paused.clear()

    def reset_stale(self):
        with self._in_flight_lock:
            self._reset([self.status_name(p) for p in self._plugins])

    def retry_stale(self):
        with self._in_flight_lock:
            quiet = [self.status_name(p) for p in self._plugins if self._no_batch_running(p)]
            reset = self._reset(quiet)
            for status_name in quiet:
                self._retried[status_name] = set(reset.get(status_name, ()))

    def _reset(self, status_names: list[str]) -> dict[str, list[str]]:
        if not status_names:
            return {}
        reset = self._writer.reset_stale(status_names, keep=self._paused)
        for status_name in status_names:
            self._in_flight.pop(status_name, None)
        return reset

    def _no_batch_running(self, plugin: str) -> bool:
        status_name = self.status_name(plugin)
        in_flight = self._in_flight.get(status_name, 0)
        if not in_flight:
            return True
        longest = in_flight * self.resolver.batch_timeout(plugin) + BATCH_GRACE_SECONDS
        return time.monotonic() - self._last_sent.get(status_name, 0.0) >= longest

    def _start_workers(self):
        my_pid = str(os.getpid())
        singleton_parent = str(self._tray_pid) if self._tray_pid else my_pid
        for plugin in self._per_indexer:
            self._worker_procs[plugin] = self._launch(plugin, my_pid)
        for plugin in self._plugins:
            if plugin not in self._per_indexer:
                self._launch(plugin, singleton_parent)
        if self._plugins:
            AppLogger.info(f"{self._tag} Started {self.KIND}s: {self._plugins}")

    def _launch(self, plugin: str, parent_pid: str):
        return AppProcess.new_main(f"--{self.KIND}", self._db_name, "--plugin", plugin, "--parent-pid", parent_pid)

    def _terminate_workers(self):
        for plugin in self._per_indexer:
            self._request_shutdown(plugin)
        for plugin in self._wait_stopped(WORKER_SHUTDOWN_TIMEOUT):
            AppProcess.terminate_cmd(f"--{self.KIND}", self._db_name, "--plugin", plugin, recursive=True)
        AppLogger.info(f"{self._tag} Terminated per-indexer {self.KIND}s for db={self._db_name}")

    def _request_shutdown(self, plugin: str):
        if self._node is None:
            return
        self._node.send(
            "worker.shutdown",
            {"plugin": plugin},
            dst=f"{self.KIND}-{plugin}",
            db=self._db_name,
        )

    def _wait_stopped(self, timeout: float) -> list[str]:
        return wait_workers_stopped(self.KIND, self._db_name, self._worker_procs, timeout)

    def _dispatch_loop(self):
        try:
            self.reset_stale()
        except Exception as e:
            AppLogger.error(f"{self._tag} reset_stale failed: {e}", exc=e)
        while not self._stop.is_set():
            self._dispatch_event.wait(timeout=_DISPATCH_INTERVAL)
            self._dispatch_event.clear()
            if self._stop.is_set():
                break
            try:
                self._dispatch_pending()
            except Exception as e:
                AppLogger.error(f"{self._tag} _dispatch_pending failed: {e}", exc=e)

    @profiler.profile
    def _dispatch_pending(self):
        for plugin in self._plugins:
            dst = f"{self.KIND}-{plugin}"
            if self._node.nudge_undelivered(self.BATCH_TOPIC, dst=dst, db=self._db_name):
                continue
            status_name = self.status_name(plugin)
            if self._in_flight.get(status_name, 0) >= MAX_IN_FLIGHT_BATCHES:
                continue
            rows = self._read_pending(status_name, self.resolver.batch_size(plugin))
            if not rows:
                continue
            batch = self._build_batch(plugin, status_name, rows)
            if not batch:
                continue
            paths = batch["paths"]
            with self._in_flight_lock:
                # Before the batch leaves, not through the scheduler: a mark that runs later would
                # turn a source set pending again meanwhile into 'dispatched' with no batch behind it.
                self._writer.mark_dispatched(paths, status_name)
                try:
                    self._node.send_reliable(self.BATCH_TOPIC, batch, dst=dst, db=self._db_name)
                except Exception:
                    self._writer.unmark_dispatched(paths, status_name)
                    raise
                self._in_flight[status_name] = self._in_flight.get(status_name, 0) + 1
                self._last_sent[status_name] = time.monotonic()
                self._paused.get(status_name, set()).difference_update(paths)
                retried = self._retried.get(status_name, set())
                is_retry = retried.issuperset(paths)
                retried.difference_update(paths)
            if is_retry:
                AppLogger.info(f"{self._tag} Sent {len(paths)} paths to {dst} again")
                continue
            self._scheduler.note_activity()
            self._progress.increment(0, len(paths))
            AppLogger.info(f"{self._tag} Sent {len(paths)} paths to {dst}")

    def _read_pending(self, status_name: str, limit: int) -> list[tuple]:
        return read_pending_sources(self._read_conn, status_name, limit)

    def _build_batch(self, plugin: str, status_name: str, rows: list[tuple]) -> dict | None:
        return {
            "paths": [row[0] for row in rows],
            "file_info": {row[0]: (row[1], row[2], row[3]) for row in rows},
        }
