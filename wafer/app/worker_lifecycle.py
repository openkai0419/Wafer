import concurrent.futures
import queue
import signal
import threading
from collections.abc import Callable

from ..core.ipc.node import Node
from ..core.ipc.transport import BROKER_LOST_TIMEOUT
from ..core.logs import AppLogger

_SHUTDOWN_WAIT = 5


class PluginWorkerLifecycle:
    """Shared stop/shutdown sequencing for the collector and parser worker processes.

    shutdown_plugin() runs before executor.shutdown(wait=True) so an in-flight
    plugin call gets interrupted rather than awaited; plugins that touch shared
    mutable state (pipes, readers) must guard against shutdown() running
    concurrently with their own work.
    """

    def __init__(
        self,
        get_plugin: Callable[[], object],
        registry,
        plugin_name: str,
        executor: concurrent.futures.ThreadPoolExecutor,
        label: str,
    ):
        self._get_plugin = get_plugin
        self._registry = registry
        self._plugin_name = plugin_name
        self._executor = executor
        self._label = label
        self._plugin_shutdown = threading.Event()

    def shutdown_plugin(self):
        if self._plugin_shutdown.is_set():
            return
        self._plugin_shutdown.set()
        try:
            self._get_plugin().shutdown()
        except Exception as e:
            AppLogger.warning(f"[{self._label}] plugin shutdown failed: {self._plugin_name}", exc=e)
        finally:
            self._registry.discard_instance(self._plugin_name)

    def stop(self):
        self.shutdown_plugin()
        self._executor.shutdown(wait=True, cancel_futures=True)


def cancel_not_started(futures: dict, not_done) -> set:
    return {futures[f] for f in not_done if f.cancel()}


def failed_results(paths, results, not_started=()) -> list[dict]:
    """Paths left out stay 'dispatched' and go back to pending through reset_stale_dispatched."""
    reported = {r.get("source") for r in results}
    reported.update(not_started)
    return [{"source": p, "status": False} for p in paths if p not in reported]


class PluginWorker:
    KIND = ""
    BATCH_TOPIC = ""
    RESULT_TOPIC = ""
    resolver = None

    def __init__(self, db_name: str, plugin_name: str):
        self.db_name = db_name
        self.plugin_name = plugin_name
        self.status_name = plugin_name
        self.label = self.KIND.capitalize()
        self._plugin = self.resolver.registry.instance(plugin_name)
        if not self._plugin:
            raise ValueError(f"Unknown {self.KIND} plugin: {plugin_name}")
        self._singleton = plugin_name in self.resolver.singleton_names()
        node_db = "" if self._singleton else db_name
        self._node = Node(f"{self.KIND}-{plugin_name}", db=node_db, consumer=True, outbox_poll=None, broker_lost_timeout=BROKER_LOST_TIMEOUT)
        self._node.subscribe(self.BATCH_TOPIC, self._handle_batch)
        self._node.subscribe("plugin.notify", self._on_notify)
        self._node.subscribe("worker.shutdown", self._on_shutdown)
        self._max_workers = self.resolver.max_workers(plugin_name)
        self._batch_timeout = self.resolver.batch_timeout(plugin_name)
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=self._max_workers)
        self._stop = threading.Event()
        self._lifecycle = PluginWorkerLifecycle(lambda: self._plugin, self.resolver.registry, plugin_name, self._executor, self.label)
        self._batch_queue: queue.Queue = queue.Queue()
        self._batch_thread = threading.Thread(target=self._batch_loop, daemon=True)

    def process_path(self, path: str, file_info: tuple, metadata: dict) -> list[dict]:
        raise NotImplementedError

    def start(self):
        self._node.start()
        self._batch_thread.start()
        AppLogger.set_node(self._node, role=f"{self.KIND}-{self.plugin_name}")
        AppLogger.info(f"{type(self).__name__} started: plugin={self.plugin_name} db={self.db_name}")

    def stop(self):
        self._stop.set()
        self._batch_queue.put(None)
        self._lifecycle.stop()
        if self._batch_thread.is_alive():
            self._batch_thread.join(timeout=_SHUTDOWN_WAIT)
        self._node.stop()
        AppLogger.info(f"{type(self).__name__} stopped: plugin={self.plugin_name}")

    def wait(self):
        self._stop.wait()

    def _on_notify(self, msg) -> bool:
        self._plugin.on_notify(msg.payload if isinstance(msg.payload, dict) else None)
        AppLogger.info(f"[{self.label}] Notified: {self.plugin_name}")
        return True

    def _on_shutdown(self, msg) -> bool:
        self._stop.set()
        self._batch_queue.put(None)
        AppLogger.info(f"[{self.label}] Shutdown requested: {self.plugin_name}")
        return True

    def _handle_batch(self, msg) -> bool:
        if self._stop.is_set():
            return True
        payload = msg.payload
        if not isinstance(payload, dict):
            AppLogger.warning(f"{self.BATCH_TOPIC}: invalid payload type: {type(payload)}")
            return True
        paths = payload.get("paths", [])
        if not paths:
            return True
        self._batch_queue.put((paths, payload.get("file_info", {}), payload.get("metadata", {}), msg.db))
        return True

    def _batch_loop(self):
        while not self._stop.is_set():
            try:
                item = self._batch_queue.get(timeout=1.0)
            except queue.Empty:
                continue
            if item is None:
                break
            self._process_batch(*item)

    def _process_batch(self, paths, file_info_raw, metadata, db):
        try:
            file_info = {p: tuple(v) for p, v in file_info_raw.items()}

            def process_one(p):
                try:
                    return self.process_path(p, file_info.get(p, (0.0, 0)), metadata.get(p, {}))
                except Exception as e:
                    AppLogger.warning(f"[{self.label}] process failed: {p}: {e}", exc=e)
                    return []

            futures = {self._executor.submit(process_one, p): p for p in paths}
            done, not_done = concurrent.futures.wait(futures, timeout=self._batch_timeout)
            results = []
            for fut in done:
                try:
                    results.extend(fut.result())
                except Exception as e:
                    AppLogger.warning(f"[{self.label}] future failed: {futures[fut]}: {e}", exc=e)
            not_started = cancel_not_started(futures, not_done)
            if not_done:
                AppLogger.warning(f"[{self.label}] batch timeout: {len(not_done) - len(not_started)}/{len(paths)} unfinished, {len(not_started)} not started (retried later)")
            failures = failed_results(paths, results, not_started)
            if failures and self._stop.is_set():
                AppLogger.info(f"[{self.label}] Stopping: {len(failures)} paths without a result are retried later")
            else:
                results.extend(failures)
            self._node.send_reliable(
                self.RESULT_TOPIC,
                {self.KIND: self.status_name, "results": results},
                dst="indexer",
                db=db,
            )
            AppLogger.info(f"[{self.label}] Sent {len(results)} results for db={db}")
        except Exception as e:
            AppLogger.error(f"[{self.label}] _process_batch failed: {e}", exc=e)

    @classmethod
    def run(cls, db_name: str, plugin_name: str, parent_pid: int | None = None):
        from ..constants import APP_DATA_DIR_NAME
        from ..core.platform.process_checker import ParentProcessChecker
        from ..core.platform.process_lock import SafeProcessLock

        label = cls.KIND.capitalize()
        lock_name = f"{APP_DATA_DIR_NAME}_{cls.KIND}_{plugin_name}"
        if plugin_name not in cls.resolver.singleton_names():
            lock_name = f"{lock_name}_{db_name}"
        try:
            with SafeProcessLock(lock_name, parent_pid=parent_pid):
                worker = cls(db_name, plugin_name)
                worker.start()
                signal.signal(signal.SIGINT, lambda s, f: worker._stop.set())
                signal.signal(signal.SIGTERM, lambda s, f: worker._stop.set())

                checker = None
                if parent_pid is not None:
                    checker = ParentProcessChecker(parent_pid, on_orphan=lambda: worker._stop.set())
                    checker.start()
                worker._node.on_broker_lost(lambda: worker._stop.set())

                AppLogger.info(f"[{label}] Running.")
                worker.wait()
                AppLogger.info(f"[{label}] Shutting down...")
                worker.stop()

                if checker:
                    checker.stop()
        except FileExistsError:
            AppLogger.info(f"{label} '{plugin_name}' for '{db_name}' is already running.")
