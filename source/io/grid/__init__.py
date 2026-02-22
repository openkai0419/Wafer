from ..registry import PluginRegistry
from .base import BaseGridPlugin
from .image import ImageGridPlugin
from .fallback import FallbackGridPlugin

grid_registry = PluginRegistry()
grid_registry.register(ImageGridPlugin)
grid_registry.register(FallbackGridPlugin)


def load(path: str, size=None):
    plugin_cls = grid_registry.resolve(path)
    if plugin_cls is None:
        return None
    return plugin_cls().load(path, size)
