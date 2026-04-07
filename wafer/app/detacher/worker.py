import concurrent.futures
import signal
import threading

from ...utils.logs import AppLogger
from ...utils.paths import normalize_path
from ...core.ipc.node import Node
from ...plugin.detacher.handler import detacher_resolver
from ...plugin.detacher.base import DetacherResult, BaseSingletonDetacher

_MAX_WORKERS = 4


class DetacherWorker:
    def __init__(self, db_name: str, plugin_name: str):
        self.db_name = db_name
        self.plugin_name = plugin_name
        self._status_name = detacher_resolver.status_name(plugin_name)
        self._plugin = detacher_resolver.registry.instance(plugin_name)
        if not self._plugin:
            raise ValueError(f"Unknown detacher plugin: {plugin_name}")
        self._singleton = issubclass(detacher_resolver.registry.get(plugin_name), BaseSingletonDetacher)
        node_db = "" if self._singleton else db_name
        self._node = Node(f"detacher-{plugin_name}", db=node_db)
        self._node.subscribe("detach.batch", self._handle_batch)
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=_MAX_WORKERS)
        self._stop = threading.Event()

    def start(self):
        self._node.start()
        AppLogger.set_node(self._node, role=f"detacher-{self.plugin_name}")
        AppLogger.info(f"DetacherWorker started: plugin={self.plugin_name} db={self.db_name}")

    def stop(self):
        self._stop.set()
        self._executor.shutdown(wait=False)
        self._node.stop()
        AppLogger.info(f"DetacherWorker stopped: plugin={self.plugin_name}")

    def wait(self):
        self._stop.wait()

    def _handle_batch(self, msg) -> bool:
        payload = msg.payload
        if not isinstance(payload, dict):
            AppLogger.warning(f"detach.batch: invalid payload type: {type(payload)}")
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
                    d = result.to_dict() if isinstance(result, DetacherResult) else result
                    return d
                except Exception as e:
                    AppLogger.warning(f"[Detacher] process failed: {p}: {e}", exc=e)
                    return {}

            results_raw = list(self._executor.map(process_one, paths))
            results = [r for r in results_raw if r]
            if not results:
                return
            self._node.send_reliable(
                "detach.result",
                {"detacher": self._status_name, "results": results},
                dst="indexer",
                db=db,
            )
            AppLogger.info(f"[Detacher] Sent {len(results)} results for db={db}")
        except Exception as e:
            AppLogger.error(f"[Detacher] _process_batch failed: {e}", exc=e)


def run_detacher(db_name: str, plugin_name: str, parent_pid: int | None = None):
    from ...utils.process_lock import SafeProcessLock
    from ...constants import APP_DATA_DIR_NAME
    from ...core.platform.process_checker import ParentProcessChecker

    singleton = issubclass(detacher_resolver.registry.get(plugin_name), BaseSingletonDetacher)
    if singleton:
        lock_name = f"{APP_DATA_DIR_NAME}_detacher_{plugin_name}"
    else:
        lock_name = f"{APP_DATA_DIR_NAME}_detacher_{plugin_name}_{db_name}"
    try:
        with SafeProcessLock(lock_name, parent_pid=parent_pid):
            worker = DetacherWorker(db_name, plugin_name)
            worker.start()

            def shutdown():
                AppLogger.info("[Detacher] Shutting down...")
                worker.stop()

            signal.signal(signal.SIGINT, lambda s, f: shutdown())
            signal.signal(signal.SIGTERM, lambda s, f: shutdown())

            checker = None
            if parent_pid is not None:
                checker = ParentProcessChecker(parent_pid, on_orphan=shutdown)
                checker.start()

            AppLogger.info("[Detacher] Running.")
            worker.wait()

            if checker:
                checker.stop()
    except FileExistsError:
        AppLogger.info(f"Detacher '{plugin_name}' for '{db_name}' is already running.")
