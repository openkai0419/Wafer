from ...core.logs import AppLogger
from ...plugin.collector.base import BaseCollector, CollectorResult
from ...plugin.collector.handler import collector_resolver
from ..worker_lifecycle import PluginWorker


def result_dicts(results) -> list[dict]:
    return [r.to_dict() if isinstance(r, CollectorResult) else r for r in results or () if r is not None]


class CollectorWorker(PluginWorker):
    KIND = "collector"
    BATCH_TOPIC = "collect.batch"
    RESULT_TOPIC = "collect.result"
    PLUGIN_BASE = BaseCollector
    resolver = collector_resolver
    result_dicts = staticmethod(result_dicts)

    def __init__(self, db_name: str, plugin_name: str):
        super().__init__(db_name, plugin_name)
        self._node.subscribe("service.request", self._on_service_request)

    def process_path(self, path, file_info, metadata) -> list[dict]:
        result = self._plugin.process(path, file_info)
        return result_dicts(result if isinstance(result, list) else [result])

    def process_paths(self, paths, file_info, metadata) -> list[dict]:
        return result_dicts(self._plugin.process_batch(paths, file_info))

    def _on_service_request(self, msg) -> bool:
        action = msg.payload.get("action", "") if isinstance(msg.payload, dict) else ""
        payload = msg.payload if isinstance(msg.payload, dict) else {}
        try:
            result = self._plugin.on_request(action, payload, msg)
        except Exception as e:
            AppLogger.warning(f"[Collector] on_request failed: {action}", exc=e)
            result = {"error": str(e)}
        self._node.enqueue(msg.reply(result))
        return True


run_collector = CollectorWorker.run
