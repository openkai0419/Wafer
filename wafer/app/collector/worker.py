from ...core.logs import AppLogger
from ...plugin.collector.base import CollectorResult
from ...plugin.collector.handler import collector_resolver
from ..worker_lifecycle import PluginWorker


class CollectorWorker(PluginWorker):
    KIND = "collector"
    BATCH_TOPIC = "collect.batch"
    RESULT_TOPIC = "collect.result"
    resolver = collector_resolver

    def __init__(self, db_name: str, plugin_name: str):
        super().__init__(db_name, plugin_name)
        self._node.subscribe("service.request", self._on_service_request)

    def process_path(self, path, file_info, metadata) -> list[dict]:
        result = self._plugin.process(path, file_info)
        items = result if isinstance(result, list) else [result]
        return [r.to_dict() if isinstance(r, CollectorResult) else r for r in items if r is not None]

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
