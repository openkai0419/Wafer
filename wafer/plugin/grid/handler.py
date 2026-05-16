from PySide6 import QtCore, QtGui

from ...core.files.render_target import RenderPlan, ResolveContext, SURFACE_GRID
from ...utils.profiling import profiler
from ..registry import FilePluginRegistry
from ..imageloader.base import BaseImageLoader
from .base import BaseGridPlugin, WidgetGridPlugin

VIEWER_THUMBNAIL_DEFAULT_SIZE = 512

WIDGET = "widget"
IMAGE = "image"


class GridResolver:
    def __init__(self):
        self.registry = FilePluginRegistry()
        self.thumbnail_size = VIEWER_THUMBNAIL_DEFAULT_SIZE

    @profiler.profile
    def resolve(self, path: str) -> type[BaseGridPlugin] | None:
        return self.registry.resolve(path)

    def resolve_merged_chain(self, path: str) -> list[tuple[type, str]]:
        from ..imageloader.handler import image_loader_resolver

        widget_chain = [cls for cls in self.registry.resolve_chain(path) if issubclass(cls, WidgetGridPlugin)]
        loader_chain = image_loader_resolver.registry.resolve_chain(path)
        merged = [(cls, WIDGET) for cls in widget_chain] + [(cls, IMAGE) for cls in loader_chain]
        merged.sort(key=lambda x: (x[0].PRIORITY, x[1] == WIDGET), reverse=True)
        return merged

    def resolve_plan(self, path: str, context: ResolveContext | None = None) -> RenderPlan[WidgetGridPlugin | BaseImageLoader]:
        from ..imageloader.handler import image_loader_resolver

        context = context or ResolveContext.create(path, surface=SURFACE_GRID, resolver=self.resolve_plan)
        for plugin_cls, kind in self.resolve_merged_chain(path):
            if kind == WIDGET:
                instance = self.registry.instance(plugin_cls.NAME)
            else:
                instance = image_loader_resolver.registry.instance(plugin_cls.NAME)
            if not isinstance(instance, (WidgetGridPlugin, BaseImageLoader)):
                continue
            plan = instance.resolve(path, context)
            if isinstance(plan, RenderPlan) and isinstance(plan.handler, (WidgetGridPlugin, BaseImageLoader)):
                return plan
        raise LookupError(f"no grid plugin resolved: {path}")

    def is_widget_plugin(self, path: str) -> bool:
        return isinstance(self.resolve_plan(path).handler, WidgetGridPlugin)

    @profiler.profile
    def load(self, path: str, size: QtCore.QSize | None = None) -> QtGui.QImage | None:
        from ..imageloader.handler import image_loader_resolver

        int_size = max(size.width(), size.height()) if size is not None else self.thumbnail_size
        qimage = image_loader_resolver.load_qimage(path, int_size)
        if qimage is None or qimage.isNull():
            return None
        if size is not None:
            qimage = qimage.scaled(size, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        return qimage


grid_resolver = GridResolver()


def load_thumbnail(path: str, size=None):
    return grid_resolver.load(path, size)


class WidgetNotifier:
    def __init__(self, registry: FilePluginRegistry):
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
        self._notify(index, "appear", widget)

    @profiler.profile
    def disappear(self, index: int, widget):
        self._notify(index, "disappear", widget)

    @profiler.profile
    def select(self, index: int, widget):
        self._notify(index, "select", widget)

    @profiler.profile
    def deselect(self, index: int, widget):
        self._notify(index, "deselect", widget)

    def clear(self):
        self._names.clear()
