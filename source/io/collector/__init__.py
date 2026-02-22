from ..registry import PluginRegistry
from .base import BaseCollectorPlugin, CollectorResult
from .image import ImageCollectorPlugin

collector_registry = PluginRegistry()
collector_registry.register(ImageCollectorPlugin)


def get_collector_names():
    return collector_registry.names()


def get_collector_info():
    return collector_registry.info()


def get_collectors_for_path(path):
    return [p.NAME for p in collector_registry.resolve_all(path)]
