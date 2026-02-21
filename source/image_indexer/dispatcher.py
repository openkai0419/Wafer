import os
import threading

from ..common.logs import AppLogger
from ..common.profiling import profiler
from ..db.indexer import FileIndexer
from ..os.process import Proc
from ..image_collector.plugin import get_collector_names

_BATCH_SIZE = 1000
_DISPATCH_INTERVAL = 2.0


class CollectorDispatcher:

    def __init__(self, db_name: str, indexer: FileIndexer, collectors=None):
        self._db_name = db_name
        self._indexer = indexer
        self._collectors = list(collectors or get_collector_names())
        self._node = None
        self._stop = threading.Event()
        self._dispatch_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, node):
        self._node = node
        self._reset_stale()
        self._start_collector_processes()
        self._thread = threading.Thread(target=self._dispatch_loop, daemon=True)
        self._thread.start()

    def _reset_stale(self):
        with self._indexer as idx:
            idx.db.reset_stale_dispatched(self._collectors)

    def stop(self):
        self._stop.set()
        self._dispatch_event.set()
        self._terminate_collectors()

    def request_dispatch(self):
        self._dispatch_event.set()

    def _start_collector_processes(self):
        my_pid = str(os.getpid())
        for plugin in self._collectors:
            Proc.new_main(
                '--collector', self._db_name,
                '--plugin', plugin,
                '--parent-pid', my_pid,
            )
        AppLogger.info(f'[Dispatcher] Started collectors: {self._collectors}')

    def _terminate_collectors(self):
        for plugin in self._collectors:
            Proc.terminate_cmd('--collector', self._db_name, '--plugin', plugin)
        AppLogger.info(f'[Dispatcher] Terminated collectors for db={self._db_name}')

    def _dispatch_loop(self):
        while not self._stop.is_set():
            self._dispatch_event.wait(timeout=_DISPATCH_INTERVAL)
            self._dispatch_event.clear()
            if self._stop.is_set():
                break
            self._dispatch_pending()

    @profiler.profile
    def _dispatch_pending(self):
        with self._indexer as idx:
            for collector in self._collectors:
                pending = idx.db.get_pending_sources(collector, limit=_BATCH_SIZE)
                if not pending:
                    continue
                paths = [row[0] for row in pending]
                file_info = {row[0]: (row[1], row[2], row[3]) for row in pending}
                idx.db.mark_dispatched(paths, collector)
                self._node.send(
                    'collect.batch',
                    {'paths': paths, 'file_info': file_info},
                    dst=f'collector-{collector}',
                    db=self._db_name,
                )
                AppLogger.info(f'[Dispatcher] Sent {len(paths)} paths to collector-{collector}')
