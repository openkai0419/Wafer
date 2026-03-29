from ..registry import FilePluginRegistry
from .base import BaseCollectorPlugin, BaseSingletonCollector, CollectorResult


class CollectorResolver:

    def __init__(self):
        self.registry = FilePluginRegistry()

    def names(self):
        return self.registry.names()

    def summary(self):
        return self.registry.summary()

    def collectors_for_path(self, path):
        return [p.NAME for p in self.registry.resolve_all(path)]

    def singleton_names(self) -> list[str]:
        return [p.NAME for p in self.registry.list_all() if issubclass(p, BaseSingletonCollector)]

    def per_indexer_names(self) -> list[str]:
        return [p.NAME for p in self.registry.list_all() if not issubclass(p, BaseSingletonCollector)]

    def batch_size(self, name: str) -> int:
        cls = self.registry.get(name)
        return getattr(cls, 'BATCH_SIZE', 1200) if cls else 1200


collector_resolver = CollectorResolver()
