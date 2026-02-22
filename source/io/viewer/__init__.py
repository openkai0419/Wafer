from ..registry import PluginRegistry
from .base import BaseViewerPlugin
from .image import ImageViewerPlugin

viewer_registry = PluginRegistry()
viewer_registry.register(ImageViewerPlugin)


def resolve_viewer(path: str) -> type[BaseViewerPlugin] | None:
    return viewer_registry.resolve(path)
