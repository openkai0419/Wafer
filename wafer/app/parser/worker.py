from ...plugin.parser.base import ParserResult
from ...plugin.parser.handler import parser_resolver
from ..worker_lifecycle import PluginWorker


class ParserWorker(PluginWorker):
    KIND = "parser"
    BATCH_TOPIC = "parse.batch"
    RESULT_TOPIC = "parse.result"
    resolver = parser_resolver

    def __init__(self, db_name: str, plugin_name: str):
        super().__init__(db_name, plugin_name)
        self.status_name = self.resolver.status_name(plugin_name)
        if not self._singleton:
            self._plugin.db_name = db_name

    def process_path(self, path, file_info, metadata) -> list[dict]:
        result = self._plugin.process(path, file_info, metadata)
        result = result.to_dict() if isinstance(result, ParserResult) else result
        return [result] if result else []


run_parser = ParserWorker.run
