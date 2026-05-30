from ..registry import PluginRegistry
from .base import BaseSingletonParser


class ParserResolver:
    def __init__(self):
        self.registry = PluginRegistry()

    def names(self):
        return self.registry.names()

    def summary(self):
        return self.registry.summary()

    def singleton_names(self) -> list[str]:
        return [p.NAME for p in self.registry.list_all() if issubclass(p, BaseSingletonParser)]

    def per_indexer_names(self) -> list[str]:
        return [p.NAME for p in self.registry.list_all() if not issubclass(p, BaseSingletonParser)]

    def batch_size(self, name: str) -> int:
        cls = self.registry.get(name)
        return getattr(cls, "BATCH_SIZE", 1200) if cls else 1200

    def max_workers(self, name: str) -> int:
        cls = self.registry.get(name)
        return max(1, int(getattr(cls, "MAX_WORKERS", 1))) if cls else 1

    def batch_timeout(self, name: str) -> float:
        cls = self.registry.get(name)
        return float(getattr(cls, "MAX_TIMEOUT", 300.0)) if cls else 300.0

    def trigger_keys(self, name: str) -> tuple[str, ...]:
        cls = self.registry.get(name)
        return getattr(cls, "TRIGGER_KEYS", ()) if cls else ()

    def parsers_for_keys(self, keys: set[str]) -> list[str]:
        result = []
        for cls in self.registry.list_all():
            tk = getattr(cls, "TRIGGER_KEYS", ())
            if tk and keys & set(tk):
                result.append(cls.NAME)
        return result

    def status_name(self, name: str) -> str:
        return name


parser_resolver = ParserResolver()
