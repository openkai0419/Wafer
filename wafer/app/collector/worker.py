import concurrent.futures
import queue
import signal
import threading

from ...utils.logs import AppLogger
from ...utils.paths import normalize_path
from ...core.ipc.node import Node
from ...plugin.collector.handler import collector_resolver
from ...plugin.collector.base import CollectorResult, BaseSingletonCollector

_MAX_WORKERS = 4
_CHUNK_TIMEOUT = 120
_CHUNK_SIZE = 50
_SHUTDOWN_WAIT = 5


class CollectorWorker:
    def __init__(self, db_name: str, plugin_name: str):
        self.db_name = db_name
        self.plugin_name = plugin_name
        self._plugin = collector_resolver.registry.instance(plugin_name)
        if not self._plugin:
            raise ValueError(f"Unknown plugin: {plugin_name}")
        self._singleton = issubclass(collector_resolver.registry.get(plugin_name), BaseSingletonCollector)
        node_db = "" if self._singleton else db_name
        self._node = Node(f"collector-{plugin_name}", db=node_db)
        self._node.subscribe("collect.batch", self._handle_batch)
        self._node.subscribe("plugin.notify", self._on_notify)
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=_MAX_WORKERS)
        self._stop = threading.Event()
        self._batch_queue: queue.Queue = queue.Queue()
        self._batch_thread = threading.Thread(target=self._batch_loop, daemon=True)

    def start(self):
        self._node.start()
        self._batch_thread.start()
        AppLogger.set_node(self._node, role=f"collector-{self.plugin_name}")
        AppLogger.info(f"CollectorWorker started: plugin={self.plugin_name} db={self.db_name}")

    def stop(self):
        self._stop.set()
        self._batch_queue.put(None)
        self._executor.shutdown(wait=True, cancel_futures=True)
        self._node.stop()
        AppLogger.info(f"CollectorWorker stopped: plugin={self.plugin_name}")

    def wait(self):
        self._stop.wait()

    def _on_notify(self, msg) -> bool:
        self._plugin.on_notify()
        AppLogger.info(f"[Collector] Notified: {self.plugin_name}")
        return True

    def _handle_batch(self, msg) -> bool:
        if self._stop.is_set():
            return True
        payload = msg.payload
        if not isinstance(payload, dict):
            AppLogger.warning(f"collect.batch: invalid payload type: {type(payload)}")
            return True
        paths = payload.get("paths", [])
        file_info_raw = payload.get("file_info", {})
        if not paths:
            return True
        self._batch_queue.put((paths, file_info_raw, msg.db))
        return True

    def _batch_loop(self):
        while not self._stop.is_set():
            try:
                item = self._batch_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            if item is None:
                break
            paths, file_info_raw, db = item
            self._process_batch(paths, file_info_raw, db)

    def _process_batch(self, paths, file_info_raw, db):
        try:
            file_info = {p: tuple(v) for p, v in file_info_raw.items()}

            def process_one(p):
                try:
                    info = file_info.get(p, (0.0, 0))
                    result = self._plugin.process(normalize_path(p), info)
                    items = result if isinstance(result, list) else [result]
                    dicts = [r.to_dict() if isinstance(r, CollectorResult) else r for r in items]
                    fh = info[2] if len(info) > 2 else None
                    if fh:
                        for d in dicts:
                            if d.get("tags") and not d.get("file_hash"):
                                d["file_hash"] = fh
                    return dicts
                except Exception as e:
                    AppLogger.warning(f"[Collector] process failed: {p}: {e}", exc=e)
                    return []

            all_results = []
            for i in range(0, len(paths), _CHUNK_SIZE):
                if self._stop.is_set():
                    break
                chunk = paths[i : i + _CHUNK_SIZE]
                futures = {self._executor.submit(process_one, p): p for p in chunk}
                done, not_done = concurrent.futures.wait(futures, timeout=_CHUNK_TIMEOUT)
                for fut in done:
                    try:
                        all_results.extend(fut.result())
                    except Exception as e:
                        AppLogger.warning(f"[Collector] future failed: {futures[fut]}: {e}", exc=e)
                if not_done:
                    AppLogger.warning(f"[Collector] chunk timeout: {len(not_done)}/{len(chunk)} unfinished")
                    for fut in not_done:
                        fut.cancel()
            self._node.send_reliable(
                "collect.result",
                {"collector": self.plugin_name, "results": all_results},
                dst="indexer",
                db=db,
            )
            AppLogger.info(f"[Collector] Sent {len(all_results)} results for db={db}")
        except Exception as e:
            AppLogger.error(f"[Collector] _process_batch failed: {e}", exc=e)


def run_collector(db_name: str, plugin_name: str, parent_pid: int | None = None):
    from ...utils.process_lock import SafeProcessLock
    from ...constants import APP_DATA_DIR_NAME
    from ...core.platform.process_checker import ParentProcessChecker

    singleton = issubclass(collector_resolver.registry.get(plugin_name), BaseSingletonCollector)
    if singleton:
        lock_name = f"{APP_DATA_DIR_NAME}_collector_{plugin_name}"
    else:
        lock_name = f"{APP_DATA_DIR_NAME}_collector_{plugin_name}_{db_name}"
    try:
        with SafeProcessLock(lock_name, parent_pid=parent_pid):
            worker = CollectorWorker(db_name, plugin_name)
            worker.start()
            shutdown_once = threading.Event()

            def shutdown():
                if shutdown_once.is_set():
                    return
                shutdown_once.set()
                AppLogger.info("[Collector] Shutting down...")
                worker.stop()

            signal.signal(signal.SIGINT, lambda s, f: worker._stop.set())
            signal.signal(signal.SIGTERM, lambda s, f: worker._stop.set())

            checker = None
            if parent_pid is not None:
                checker = ParentProcessChecker(parent_pid, on_orphan=lambda: worker._stop.set())
                checker.start()

            AppLogger.info("[Collector] Running.")
            worker.wait()
            shutdown()

            if checker:
                checker.stop()
    except FileExistsError:
        AppLogger.info(f"Collector '{plugin_name}' for '{db_name}' is already running.")
