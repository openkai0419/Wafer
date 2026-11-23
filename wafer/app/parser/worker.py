from ...plugin.parser.base import BaseParser, ParserResult
from ...plugin.parser.handler import parser_resolver
from ..worker_lifecycle import PluginWorker


class ParserWorker(PluginWorker):
    KIND = "parser"
    BATCH_TOPIC = "parse.batch"
    RESULT_TOPIC = "parse.result"
    PLUGIN_BASE = BaseParser
    resolver = parser_resolver

    def __init__(self, db_name: str, plugin_name: str):
        super().__init__(db_name, plugin_name)
        self.status_name = self.resolver.status_name(plugin_name)
        if not self._singleton:
            self._plugin.db_name = db_name

    def process_path(self, path, file_info, metadata) -> list[dict]:
        return result_dicts([self._plugin.process(path, file_info, metadata)])

    def process_paths(self, paths, file_info, metadata) -> list[dict]:
        return result_dicts(self._plugin.process_batch(paths, file_info, metadata))


def result_dicts(results) -> list[dict]:
    return [r.to_dict() if isinstance(r, ParserResult) else r for r in results if r]


run_parser = ParserWorker.run
