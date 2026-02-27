from ..registry import PluginRegistry
from .base import BaseCollectorPlugin, CollectorResult


class CollectorHandler:

    def __init__(self):
        self.registry = PluginRegistry()

    def names(self):
        return self.registry.names()

    def info(self):
        return self.registry.info()

    def collectors_for_path(self, path):
        return [p.NAME for p in self.registry.resolve_all(path)]


collector_handler = CollectorHandler()
