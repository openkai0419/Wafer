import concurrent.futures
import signal
import threading

from ...utils.logs import AppLogger
from ...utils.paths import normalize_path
from ...core.ipc.node import Node
from ...core.ipc.transport import BROKER_LOST_TIMEOUT
from ...plugin.parser.handler import parser_resolver
from ...plugin.parser.base import ParserResult, BaseSingletonParser

_MAX_WORKERS = 4
_TASK_TIMEOUT = 120
_SHUTDOWN_WAIT = 5


class ParserWorker:
    def __init__(self, db_name: str, plugin_name: str):
        self.db_name = db_name
        self.plugin_name = plugin_name
        self._status_name = parser_resolver.status_name(plugin_name)
        self._plugin = parser_resolver.registry.instance(plugin_name)
        if not self._plugin:
            raise ValueError(f"Unknown parser plugin: {plugin_name}")
        self._singleton = issubclass(parser_resolver.registry.get(plugin_name), BaseSingletonParser)
        node_db = "" if self._singleton else db_name
        self._node = Node(f"parser-{plugin_name}", db=node_db, broker_lost_timeout=BROKER_LOST_TIMEOUT)
        self._node.subscribe("parse.batch", self._handle_batch)
        self._node.subscribe("plugin.notify", self._on_notify)
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=_MAX_WORKERS)
        self._stop = threading.Event()

    def start(self):
        self._node.start()
        AppLogger.set_node(self._node, role=f"parser-{self.plugin_name}")
        AppLogger.info(f"ParserWorker started: plugin={self.plugin_name} db={self.db_name}")

    def stop(self):
        self._stop.set()
        self._executor.shutdown(wait=True, cancel_futures=True)
        self._node.stop()
        AppLogger.info(f"ParserWorker stopped: plugin={self.plugin_name}")

    def wait(self):
        self._stop.wait()

    def _on_notify(self, msg) -> bool:
        self._plugin.on_notify(msg.payload if isinstance(msg.payload, dict) else None)
        AppLogger.info(f"[Parser] Notified: {self.plugin_name}")
        return True

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
        db = msg.db
        threading.Thread(
            target=self._process_batch,
            args=(paths, file_info_raw, metadata, db),
            daemon=True,
        ).start()
        return True

    def _process_batch(self, paths, file_info_raw, metadata, db):
        try:
            file_info = {p: tuple(v) for p, v in file_info_raw.items()}

            def process_one(p):
                try:
                    info = file_info.get(p, (0.0, 0))
                    meta = metadata.get(p, {})
                    result = self._plugin.process(normalize_path(p), info, meta)
                    d = result.to_dict() if isinstance(result, ParserResult) else result
                    return d
                except Exception as e:
                    AppLogger.warning(f"[Parser] process failed: {p}: {e}", exc=e)
                    return {}

            futures = {self._executor.submit(process_one, p): p for p in paths}
            results_raw = []
            for fut in concurrent.futures.as_completed(futures, timeout=_TASK_TIMEOUT):
                try:
                    results_raw.append(fut.result())
                except Exception as e:
                    AppLogger.warning(f"[Parser] future failed: {futures[fut]}: {e}", exc=e)
                    results_raw.append({})
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
    from ...utils.process_lock import SafeProcessLock
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
