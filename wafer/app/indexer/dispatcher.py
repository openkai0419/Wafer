from __future__ import annotations

import os
import threading
from pathlib import Path

from ...core.db.db_utils import apply_read_pragmas, connect_with_retry
from ...utils.logs import AppLogger
from ...utils.profiling import profiler
from ...core.platform.process import AppProcess
from ...plugin.collector.handler import collector_resolver
from .db_writer import DatabaseWriter
from .progress_notifier import ProgressAggregator
from .scheduler import TaskScheduler
from .task import Task, TaskPriority

_DISPATCH_INTERVAL = 2.0


class CollectorDispatcher:

    _singleton_started: set[str] = set()
    _singleton_lock = threading.Lock()

    def __init__(
        self,
        db_name: str,
        db_path: str | Path,
        scheduler: TaskScheduler,
        writer: DatabaseWriter,
        progress: ProgressAggregator,
        collectors=None,
    ):
        self._db_name = db_name
        self._db_path = Path(db_path)
        self._scheduler = scheduler
        self._writer = writer
        self._progress = progress
        self._collectors = list(collectors or collector_resolver.names())
        self._per_indexer = [c for c in self._collectors if c not in collector_resolver.singleton_names()]
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
            f'{uri}?mode=ro', timeout=1.0, uri=True, check_same_thread=False,
        )
        apply_read_pragmas(self._read_conn)
        self._reset_stale()
        self._start_collector_processes()
        self._thread = threading.Thread(target=self._dispatch_loop, daemon=True)
        self._thread.start()

    def _reset_stale(self):
        self._scheduler.submit(Task.create(
            'reset_stale',
            priority=TaskPriority.DISPATCH,
            run=lambda: self._writer.reset_stale(self._collectors),
        ))

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
        for plugin in self._per_indexer:
            AppProcess.new_main(
                '--collector', self._db_name,
                '--plugin', plugin,
                '--parent-pid', my_pid,
            )
        singletons_launched = []
        with CollectorDispatcher._singleton_lock:
            for plugin in self._collectors:
                if plugin in self._per_indexer:
                    continue
                if plugin not in CollectorDispatcher._singleton_started:
                    AppProcess.new_main(
                        '--collector', self._db_name,
                        '--plugin', plugin,
                        '--parent-pid', my_pid,
                    )
                    CollectorDispatcher._singleton_started.add(plugin)
                    singletons_launched.append(plugin)
        started = self._per_indexer + singletons_launched
        AppLogger.info(f'[Dispatcher] Started collectors: {started}')

    def _terminate_collectors(self):
        for plugin in self._per_indexer:
            AppProcess.terminate_cmd('--collector', self._db_name, '--plugin', plugin)
        AppLogger.info(f'[Dispatcher] Terminated per-indexer collectors for db={self._db_name}')

    def _dispatch_loop(self):
        while not self._stop.is_set():
            self._dispatch_event.wait(timeout=_DISPATCH_INTERVAL)
            self._dispatch_event.clear()
            if self._stop.is_set():
                break
            try:
                self._dispatch_pending()
            except Exception as e:
                AppLogger.error(f'[Dispatcher] _dispatch_pending failed: {e}', exc=e)

    @profiler.profile
    def _dispatch_pending(self):
        for collector in self._collectors:
            batch_size = collector_resolver.batch_size(collector)
            cur = self._read_conn.cursor()
            cur.execute(
                '''SELECT cs.source, s.modified, s.size
                FROM collection_status cs
                JOIN sources s ON s.source = cs.source
                WHERE cs.collector = ? AND cs.status = 'pending'
                LIMIT ?''',
                (collector, batch_size),
            )
            pending = cur.fetchall()
            cur.close()
            if not pending:
                continue
            with self._dispatched_lock:
                already = self._dispatched_paths.get(collector, set())
                rows = [row for row in pending if row[0] not in already]
            if not rows:
                continue
            paths = [row[0] for row in rows]
            file_info = {row[0]: (row[1], row[2]) for row in rows}
            with self._dispatched_lock:
                self._dispatched_paths.setdefault(collector, set()).update(paths)
            self._scheduler.submit(Task.create(
                'mark_dispatched',
                priority=TaskPriority.DISPATCH,
                run=lambda ps=paths, c=collector: self._writer.mark_dispatched(ps, c),
                on_complete=lambda c=collector, ps=paths: self._clear_dispatched(c, ps),
            ))
            self._progress.increment(0, len(paths))
            self._node.send(
                'collect.batch',
                {'paths': paths, 'file_info': file_info},
                dst=f'collector-{collector}',
                db=self._db_name,
            )
            AppLogger.info(f'[Dispatcher] Sent {len(paths)} paths to collector-{collector}')

    def _clear_dispatched(self, collector: str, paths: list[str]):
        with self._dispatched_lock:
            s = self._dispatched_paths.get(collector)
            if s:
                s.difference_update(paths)
