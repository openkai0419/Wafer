import concurrent.futures
import queue
import signal
import threading

from ...core.logs import AppLogger
from ...core.common.paths import normalize_path
from ...core.ipc.node import Node
from ...core.ipc.transport import BROKER_LOST_TIMEOUT
from ...plugin.parser.handler import parser_resolver
from ...plugin.parser.base import ParserResult, BaseSingletonParser

_SHUTDOWN_WAIT = 5


def _attach_file_hash(result: dict, info: tuple):
    if not result.get("tags") and not result.get("delete_tag_keys"):
        result.pop("file_hash", None)
        return
    file_hash = result.get("update_hash") or (info[2] if len(info) > 2 else None)
    if file_hash:
        result["file_hash"] = file_hash
    else:
        result.pop("file_hash", None)


class ParserWorker:
    def __init__(self, db_name: str, plugin_name: str):
        self.db_name = db_name
        self.plugin_name = plugin_name
        self._status_name = parser_resolver.status_name(plugin_name)
        self._plugin = parser_resolver.registry.instance(plugin_name)
        if not self._plugin:
            raise ValueError(f"Unknown parser plugin: {plugin_name}")
        self._singleton = issubclass(parser_resolver.registry.get(plugin_name), BaseSingletonParser)
        if not self._singleton:
            self._plugin.db_name = db_name
        node_db = "" if self._singleton else db_name
        self._node = Node(f"parser-{plugin_name}", db=node_db, broker_lost_timeout=BROKER_LOST_TIMEOUT)
        self._node.subscribe("parse.batch", self._handle_batch)
        self._node.subscribe("plugin.notify", self._on_notify)
        self._node.subscribe("worker.shutdown", self._on_shutdown)
        self._max_workers = parser_resolver.max_workers(plugin_name)
        self._batch_timeout = parser_resolver.batch_timeout(plugin_name)
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=self._max_workers)
        self._stop = threading.Event()
        self._plugin_shutdown = threading.Event()
        self._batch_queue: queue.Queue = queue.Queue()
        self._batch_thread = threading.Thread(target=self._batch_loop, daemon=True)

    def start(self):
        self._node.start()
        self._batch_thread.start()
        AppLogger.set_node(self._node, role=f"parser-{self.plugin_name}")
        AppLogger.info(f"ParserWorker started: plugin={self.plugin_name} db={self.db_name}")

    def stop(self):
        self._stop.set()
        self._batch_queue.put(None)
        self._executor.shutdown(wait=True, cancel_futures=True)
        if self._batch_thread.is_alive():
            self._batch_thread.join(timeout=_SHUTDOWN_WAIT)
        self._shutdown_plugin()
        self._node.stop()
        AppLogger.info(f"ParserWorker stopped: plugin={self.plugin_name}")

    def wait(self):
        self._stop.wait()

    def _on_notify(self, msg) -> bool:
        self._plugin.on_notify(msg.payload if isinstance(msg.payload, dict) else None)
        AppLogger.info(f"[Parser] Notified: {self.plugin_name}")
        return True

    def _on_shutdown(self, msg) -> bool:
        self._stop.set()
        self._batch_queue.put(None)
        AppLogger.info(f"[Parser] Shutdown requested: {self.plugin_name}")
        return True

    def _shutdown_plugin(self):
        if self._plugin_shutdown.is_set():
            return
        self._plugin_shutdown.set()
        try:
            self._plugin.shutdown()
        except Exception as e:
            AppLogger.warning(f"[Parser] plugin shutdown failed: {self.plugin_name}", exc=e)

    def _handle_batch(self, msg) -> bool:
        if self._stop.is_set():
            return True
        payload = msg.payload
        if not isinstance(payload, dict):
            AppLogger.warning(f"parse.batch: invalid payload type: {type(payload)}")
            return True
        paths = payload.get("paths", [])
        file_info_raw = payload.get("file_info", {})
        metadata = payload.get("metadata", {})
        if not paths:
            return True
        self._batch_queue.put((paths, file_info_raw, metadata, msg.db))
        return True

    def _batch_loop(self):
        while not self._stop.is_set():
            try:
                item = self._batch_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            if item is None:
                break
            paths, file_info_raw, metadata, db = item
            self._process_batch(paths, file_info_raw, metadata, db)

    def _process_batch(self, paths, file_info_raw, metadata, db):
        try:
            file_info = {p: tuple(v) for p, v in file_info_raw.items()}

            def process_one(p):
                try:
                    info = file_info.get(p, (0.0, 0))
                    meta = metadata.get(p, {})
                    result = self._plugin.process(normalize_path(p), info, meta)
                    d = result.to_dict() if isinstance(result, ParserResult) else result
                    if d:
                        _attach_file_hash(d, info)
                    return d
                except Exception as e:
                    AppLogger.warning(f"[Parser] process failed: {p}: {e}", exc=e)
                    return {}

            futures = {self._executor.submit(process_one, p): p for p in paths}
            done, not_done = concurrent.futures.wait(futures, timeout=self._batch_timeout)
            results_raw = []
            for fut in done:
                try:
                    results_raw.append(fut.result())
                except Exception as e:
                    AppLogger.warning(f"[Parser] future failed: {futures[fut]}: {e}", exc=e)
                    results_raw.append({})
            if not_done:
                AppLogger.warning(f"[Parser] batch timeout: {len(not_done)}/{len(paths)} unfinished")
                for fut in not_done:
                    fut.cancel()
            results = [r for r in results_raw if r]
            if not results:
                return
            self._node.send_reliable(
                "parse.result",
                {"parser": self._status_name, "results": results},
                dst="indexer",
                db=db,
            )
            AppLogger.info(f"[Parser] Sent {len(results)} results for db={db}")
        except Exception as e:
            AppLogger.error(f"[Parser] _process_batch failed: {e}", exc=e)


def run_parser(db_name: str, plugin_name: str, parent_pid: int | None = None):
    from ...core.platform.process_lock import SafeProcessLock
    from ...constants import APP_DATA_DIR_NAME
    from ...core.platform.process_checker import ParentProcessChecker

    singleton = issubclass(parser_resolver.registry.get(plugin_name), BaseSingletonParser)
    if singleton:
        lock_name = f"{APP_DATA_DIR_NAME}_parser_{plugin_name}"
    else:
        lock_name = f"{APP_DATA_DIR_NAME}_parser_{plugin_name}_{db_name}"
    try:
        with SafeProcessLock(lock_name, parent_pid=parent_pid):
            worker = ParserWorker(db_name, plugin_name)
            worker.start()
            shutdown_once = threading.Event()

            def shutdown():
                if shutdown_once.is_set():
                    return
                shutdown_once.set()
                AppLogger.info("[Parser] Shutting down...")
                worker.stop()

            signal.signal(signal.SIGINT, lambda s, f: worker._stop.set())
            signal.signal(signal.SIGTERM, lambda s, f: worker._stop.set())

            checker = None
            if parent_pid is not None:
                checker = ParentProcessChecker(parent_pid, on_orphan=lambda: worker._stop.set())
                checker.start()
            worker._node.on_broker_lost(lambda: worker._stop.set())

            AppLogger.info("[Parser] Running.")
            worker.wait()
            shutdown()

            if checker:
                checker.stop()
    except FileExistsError:
        AppLogger.info(f"Parser '{plugin_name}' for '{db_name}' is already running.")
