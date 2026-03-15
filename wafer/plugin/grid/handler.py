from PySide6 import QtGui

from ...utils.profiling import profiler
from ..registry import PluginRegistry
from .base import BaseGridPlugin, ImageGridPlugin, WidgetGridPlugin

VIEWER_THUMBNAIL_DEFAULT_SIZE = 512


class GridResolver:

    def __init__(self):
        self.registry = PluginRegistry()
        self.thumbnail_size = VIEWER_THUMBNAIL_DEFAULT_SIZE

    @profiler.profile
    def resolve(self, path: str) -> type[BaseGridPlugin] | None:
        return self.registry.resolve(path)

    def resolve_chain(self, path: str) -> list[type[BaseGridPlugin]]:
        return self.registry.resolve_chain(path)

    def resolve_instance(self, path: str) -> BaseGridPlugin | None:
        return self.registry.resolve_instance(path)

    def resolve_image_instance(self, path: str) -> ImageGridPlugin | None:
        for cls in self.registry.resolve_chain(path):
            inst = self.registry.instance(cls.NAME)
            if isinstance(inst, ImageGridPlugin):
                return inst
        return None

    def is_widget_plugin(self, path: str) -> bool:
        return isinstance(self.registry.resolve_instance(path), WidgetGridPlugin)

    @profiler.profile
    def load(self, path: str, size=None) -> QtGui.QImage | None:
        for plugin_cls in self.registry.resolve_chain(path):
            instance = self.registry.instance(plugin_cls.NAME)
            if isinstance(instance, ImageGridPlugin):
                result = instance.load(path, size)
                if result is not None:
                    return result
        return None


grid_resolver = GridResolver()


class WidgetNotifier:

    def __init__(self, registry: PluginRegistry):
        self._registry = registry
        self._names: dict[int, str] = {}

    def plugin_name(self, index: int) -> str | None:
        return self._names.get(index)

    @profiler.profile
    def _notify(self, index: int, method: str, widget):
        name = self._names.get(index)
        if not name:
            return
        instance = self._registry.instance(name)
        if isinstance(instance, WidgetGridPlugin):
            getattr(instance, method)(widget)

    @profiler.profile
    def bind(self, index: int, plugin_name: str):
        self._names[index] = plugin_name

    def require_thumbnail(self, plugin_name: str) -> bool:
        instance = self._registry.instance(plugin_name)
        if isinstance(instance, WidgetGridPlugin):
            return instance.REQUIRE_THUMBNAIL
        return False

    @profiler.profile
    def on_thumb_loaded(self, index: int, widget, image):
        name = self._names.get(index)
        if not name:
            return
        instance = self._registry.instance(name)
        if isinstance(instance, WidgetGridPlugin):
            instance.on_thumb_loaded(widget, image)

    @profiler.profile
    def unbind(self, index: int, widget):
        name = self._names.pop(index, None)
        if not name:
            return
        instance = self._registry.instance(name)
        if isinstance(instance, WidgetGridPlugin):
            if widget.isVisible():
                instance.disappear(widget)
            instance.release(widget)

    @profiler.profile
    def appear(self, index: int, widget):
        self._notify(index, 'appear', widget)

    @profiler.profile
    def disappear(self, index: int, widget):
        self._notify(index, 'disappear', widget)

    @profiler.profile
    def select(self, index: int, widget):
        self._notify(index, 'select', widget)

    @profiler.profile
    def deselect(self, index: int, widget):
        self._notify(index, 'deselect', widget)

    def clear(self):
        self._names.clear()
