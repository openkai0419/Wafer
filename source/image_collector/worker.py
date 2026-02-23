import concurrent.futures
import os
import signal
import threading

from ..common.logs import AppLogger
from ..common.funcs import normalize_path
from ..zmq.node import Node
from ..io.collector.handler import collector_handler
from ..io.collector.base import CollectorResult


_MAX_WORKERS = 4


class CollectorWorker:

    def __init__(self, db_name: str, plugin_name: str):
        self.db_name = db_name
        self.plugin_name = plugin_name
        plugin_cls = collector_handler.registry.get(plugin_name)
        if not plugin_cls:
            raise ValueError(f'Unknown plugin: {plugin_name}')
        self._plugin = plugin_cls()
        self._node = Node(f'collector-{plugin_name}', db=db_name)
        self._node.on('collect.batch', self._handle_batch)
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=_MAX_WORKERS)
        self._stop = threading.Event()

    def start(self):
        self._node.start()
        AppLogger.set_node(self._node, role=f'collector-{self.plugin_name}')
        AppLogger.info(f'CollectorWorker started: plugin={self.plugin_name} db={self.db_name}')

    def stop(self):
        self._stop.set()
        self._executor.shutdown(wait=False)
        self._node.stop()
        AppLogger.info(f'CollectorWorker stopped: plugin={self.plugin_name}')

    def wait(self):
        self._stop.wait()

    def _handle_batch(self, msg) -> bool:
        payload = msg.payload
        if not isinstance(payload, dict):
            AppLogger.warning(f'collect.batch: invalid payload type: {type(payload)}')
            return True
        paths = payload.get('paths', [])
        file_info_raw = payload.get('file_info', {})
        if not paths:
            return True
        threading.Thread(
            target=self._process_batch,
            args=(paths, file_info_raw),
            daemon=True,
        ).start()
        return True

    def _process_batch(self, paths, file_info_raw):
        file_info = {p: tuple(v) for p, v in file_info_raw.items()}

        def process_one(p):
            info = file_info.get(p, (0.0, 0, 0.0))
            result = self._plugin.process(normalize_path(p), info)
            items = result if isinstance(result, list) else [result]
            return [r.to_dict() if isinstance(r, CollectorResult) else r for r in items]

        nested = list(self._executor.map(process_one, paths))
        results = [item for items in nested for item in items]
        self._node.send_reliable(
            'collect.result',
            {'collector': self.plugin_name, 'results': results},
            dst='indexer',
            db=self.db_name,
        )
        AppLogger.info(f'[Collector] Sent {len(results)} results for db={self.db_name}')


def run_collector(db_name: str, plugin_name: str, parent_pid: int | None = None):
    from ..common.mutex import SafeProcessLock
    from ..constants import APP_FILE_NAME
    lock_name = f'{APP_FILE_NAME}_collector_{plugin_name}_{db_name}'
    try:
        with SafeProcessLock(lock_name, parent_pid=parent_pid):
            worker = CollectorWorker(db_name, plugin_name)
            worker.start()

            def shutdown_handler(sig, frame):
                AppLogger.info('[Collector] Shutting down...')
                worker.stop()
            signal.signal(signal.SIGINT, shutdown_handler)
            signal.signal(signal.SIGTERM, shutdown_handler)
            AppLogger.info('[Collector] Running.')
            worker.wait()
    except FileExistsError:
        AppLogger.info(f"Collector '{plugin_name}' for '{db_name}' is already running.")
