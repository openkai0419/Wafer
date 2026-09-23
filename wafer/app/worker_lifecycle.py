import concurrent.futures
import threading
from collections.abc import Callable

from ..core.logs import AppLogger


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
