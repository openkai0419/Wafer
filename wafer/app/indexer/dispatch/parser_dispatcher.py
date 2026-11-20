from __future__ import annotations

from ....core.logs import AppLogger
from ....plugin.parser.handler import parser_resolver
from .plugin_dispatcher import PluginDispatcher


class ParserDispatcher(PluginDispatcher):
    KIND = "parser"
    BATCH_TOPIC = "parse.batch"
    resolver = parser_resolver

    def status_name(self, plugin: str) -> str:
        return self.resolver.status_name(plugin)

    def _build_batch(self, plugin: str, status_name: str, rows: list[tuple]) -> dict | None:
        batch = super()._build_batch(plugin, status_name, rows)
        trigger_keys = self.resolver.trigger_keys(plugin)
        if not trigger_keys:
            batch["metadata"] = {}
            return batch
        paths = batch["paths"]
        metadata = self._writer.db.get_trigger_metadata(paths, trigger_keys)
        untriggered = [p for p in paths if p not in metadata]
        if untriggered:
            # Marked here, not through the scheduler: a mark that runs later would overwrite
            # a source set pending again meanwhile (a lost 'pending').
            self._writer.mark_collected(untriggered, status_name)
            self._scheduler.note_activity()
            paths = [p for p in paths if p in metadata]
            AppLogger.info(f"{self._tag} Skipped {len(untriggered)} paths without trigger keys for {self.KIND}-{plugin}")
        if not paths:
            return None
        return {"paths": paths, "file_info": {p: batch["file_info"][p] for p in paths}, "metadata": metadata}
