from collections.abc import Callable

from PySide6 import QtCore, QtGui

from ....utils.logs import AppLogger
from ....utils.virtual_paths import is_virtual_path
from ....core.qt.dispatcher import Dispatcher, CancelToken, CancelSlot
from ....core.files.render_target import RenderPlan
from ....plugin.grid.handler import grid_resolver
from ....plugin.grid.base import (
    WidgetGridPlugin as _WidgetGridPlugin,
    _get_error_image,
)
from ....plugin.layout.handler import layout_registry
from .cachemanager import fullsize_key


class GridPipeline(QtCore.QObject):
    layout_ready = QtCore.Signal(object)
    _image_ready = QtCore.Signal(int, str, object)

    def __init__(
        self,
        thumb_dispatcher: Dispatcher,
        render_dispatcher: Dispatcher,
        utility_dispatcher: Dispatcher,
        cache,
        widget_lookup: Callable[[int], object | None],
        promote_fn: Callable[[int, str], None],
        appear_fn: Callable[[int], None],
        parent=None,
    ):
        super().__init__(parent)
        self._thumb_dispatcher = thumb_dispatcher
        self._render_dispatcher = render_dispatcher
        self._utility_dispatcher = utility_dispatcher
        self._cache = cache
        self._widget_lookup = widget_lookup
        self._promote_fn = promote_fn
        self._appear_fn = appear_fn
        self._active: dict[int, CancelToken] = {}
        self._layout_cancel = CancelSlot()
        self._image_ready.connect(self._on_image_ready)

    def request_layout(
        self,
        aspect_ratios,
        base_height,
        spacing,
        container_width,
        container_height,
        orientation=0,
        layout_mode="justified",
    ):
        cancel = self._layout_cancel.renew()

        def task():
            if cancel.is_cancelled():
                return
            layout_cls = layout_registry.get(layout_mode)
            if layout_cls is None:
                layout_cls = layout_registry.get("justified")
            if layout_cls is None:
                AppLogger.warning(f"no layout plugin found for mode={layout_mode}")
                return
            calc = layout_cls.create_calculator(
                aspect_ratios,
                base_height,
                spacing,
                container_width,
                container_height,
                orientation,
            )
            calc.bind_cancel_token(cancel)
            calc.run()
            if cancel.is_cancelled():
                return
            layout = calc._result
            if layout is not None:
                self._utility_dispatcher.invoke(lambda l=layout: self.layout_ready.emit(l))

        self._utility_dispatcher.post(task, priority=7, cancel=cancel)

    def schedule_render(self, index: int, path: str, size: QtCore.QSize, plugin=None):
        self.cancel_index(index)

        cancel = CancelToken()
        self._active[index] = cancel

        if plugin is not None:
            if is_virtual_path(path):
                self._dispatch_resolve(index, path, size, cancel)
            elif isinstance(plugin, _WidgetGridPlugin):
                plan = RenderPlan(source=path, path=path, resolved_path=path, handler=plugin)
                self._dispatch_widget_render(index, plan, size, plugin, cancel)
            else:
                plan = RenderPlan(source=path, path=path, resolved_path=path, handler=plugin)
                self._dispatch_image_load(index, plan, size, cancel)
        else:
            self._dispatch_resolve(index, path, size, cancel)

    def _target(self, path: str) -> RenderPlan:
        return grid_resolver.resolve_plan(path)

    def _dispatch_resolve(self, index, path, size, cancel):
        def task():
            if cancel.is_cancelled():
                return
            plan = self._target(path)
            if isinstance(plan.handler, _WidgetGridPlugin):
                self._thumb_dispatcher.invoke(lambda p=plan: self._on_resolve_widget(index, p, size, p.handler, cancel))
                return
            self._load_image(index, plan, size, grid_resolver.load, cancel)

        self._render_dispatcher.post(task, priority=100, cancel=cancel)

    def _on_resolve_widget(self, index, plan: RenderPlan, size, plugin, cancel):
        if cancel.is_cancelled() or index not in self._active:
            return
        self._promote_fn(index, plugin.NAME)
        widget = self._widget_lookup(index)
        if widget is not None:
            plugin.render(widget, plan.resolved_path, size)
        self._appear_fn(index)
        if plugin.REQUIRE_THUMBNAIL:
            self._dispatch_thumbnail(index, plan, size, plugin, cancel)

    def _dispatch_widget_render(self, index, plan: RenderPlan, size, plugin, cancel):
        widget = self._widget_lookup(index)
        if widget is not None:
            plugin.render(widget, plan.resolved_path, size)
        if plugin.REQUIRE_THUMBNAIL:
            self._dispatch_thumbnail(index, plan, size, plugin, cancel)

    def _dispatch_image_load(self, index, plan: RenderPlan, size, cancel):
        path = plan.path
        fkey = fullsize_key(path)
        cached = self._cache.get_if_sufficient(fkey, size)
        if cached is None:
            cached = self._cache.get_if_sufficient(path, size)
        if cached is not None:
            widget = self._widget_lookup(index)
            if widget is not None:
                widget.set_image(cached, path)
            return
        self._render_dispatcher.post(
            lambda: self._load_image(index, plan, size, grid_resolver.load, cancel),
            priority=100,
            cancel=cancel,
        )

    def _load_image(self, index, plan: RenderPlan, size, load_fn, cancel):
        path = plan.path
        fkey = fullsize_key(path)
        cached = self._cache.get_if_sufficient(fkey, size)
        if cached is None:
            cached = self._cache.get_if_sufficient(path, size)
        if cached is not None:
            self._render_dispatcher.invoke(lambda: self._image_ready.emit(index, path, cached))
            return
        image = load_fn(plan.resolved_path, size)
        if cancel.is_cancelled():
            return
        if image is None or (isinstance(image, QtGui.QImage) and image.isNull()):
            image = _get_error_image(size)
        self._cache[path] = image
        self._render_dispatcher.invoke(lambda i=index, p=path, img=image: self._image_ready.emit(i, p, img))

    def _dispatch_thumbnail(self, index, plan: RenderPlan, size, plugin, cancel):
        path = plan.path

        def task():
            if cancel.is_cancelled():
                return
            cached = self._cache.get_if_sufficient(fullsize_key(path), size)
            if cached is None:
                cached = self._cache.get_if_sufficient(path, size)
            if cached is not None:
                self._thumb_dispatcher.invoke(lambda: self._deliver_thumbnail(index, plugin, cached))
                return
            image = grid_resolver.load(plan.resolved_path, size)
            if image is None or cancel.is_cancelled():
                return
            self._cache[path] = image
            self._thumb_dispatcher.invoke(lambda: self._deliver_thumbnail(index, plugin, image))

        self._thumb_dispatcher.post(task, priority=5, cancel=cancel)

    def _deliver_thumbnail(self, index, plugin, image):
        if index not in self._active:
            return
        widget = self._widget_lookup(index)
        if widget is not None and isinstance(widget, plugin.WIDGET_CLASS):
            plugin.on_thumb_loaded(widget, image)

    @QtCore.Slot(int, str, object)
    def _on_image_ready(self, index, path, image):
        if index not in self._active:
            return
        widget = self._widget_lookup(index)
        if widget is not None:
            widget.set_image(image, path)

    def cancel_index(self, index: int):
        token = self._active.pop(index, None)
        if token is not None:
            token.cancel()

    def cancel_all(self):
        self._layout_cancel.cancel()
        for token in self._active.values():
            token.cancel()
        self._active.clear()

    def active_count(self) -> int:
        return len(self._active)
