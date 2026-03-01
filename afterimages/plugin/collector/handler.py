from ..registry import PluginRegistry
from .base import BaseCollectorPlugin, CollectorResult


class CollectorResolver:

    def __init__(self):
        self.registry = PluginRegistry()

    def names(self):
        return self.registry.names()

    def summary(self):
        return self.registry.summary()

    def collectors_for_path(self, path):
        return [p.NAME for p in self.registry.resolve_all(path)]


collector_resolver = CollectorResolver()
