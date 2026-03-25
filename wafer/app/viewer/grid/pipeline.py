from typing import Callable, Optional

from PySide6 import QtCore, QtGui

from ....utils.logs import AppLogger
from ....core.qt.dispatcher import Dispatcher, CancelToken, CancelSlot
from ....plugin.grid.handler import grid_resolver
from ....plugin.grid.base import (
    ImageGridPlugin as _ImageGridPlugin,
    WidgetGridPlugin as _WidgetGridPlugin,
    _get_error_image,
)
from ....plugin.layout.handler import layout_registry
from ....plugin.layout.calc import LayoutData
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
        widget_lookup: Callable[[int], Optional[object]],
        promote_fn: Callable[[int, str], None],
        parent=None,
    ):
        super().__init__(parent)
        self._thumb_dispatcher = thumb_dispatcher
        self._render_dispatcher = render_dispatcher
        self._utility_dispatcher = utility_dispatcher
        self._cache = cache
        self._widget_lookup = widget_lookup
        self._promote_fn = promote_fn
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
        layout_mode='justified',
    ):
        cancel = self._layout_cancel.renew()

        def task():
            if cancel.is_cancelled():
                return
            layout_cls = layout_registry.get(layout_mode)
            if layout_cls is None:
                layout_cls = layout_registry.get('justified')
            if layout_cls is None:
                AppLogger.warning(f'no layout plugin found for mode={layout_mode}')
                return
            calc = layout_cls.create_calculator(
                aspect_ratios, base_height, spacing,
                container_width, container_height, orientation,
            )
            calc.bind_cancel_token(cancel)
            calc.run()
            if cancel.is_cancelled():
                return
            layout = calc._result
            if layout is not None:
                self.layout_ready.emit(layout)

        self._utility_dispatcher.post(task, priority=7, cancel=cancel)

    def schedule_render(self, index: int, path: str, size: QtCore.QSize, plugin=None):
        self.cancel_index(index)

        cancel = CancelToken()
        self._active[index] = cancel

        if plugin is not None:
            if isinstance(plugin, _WidgetGridPlugin):
                self._dispatch_widget_render(index, path, size, plugin, cancel)
            else:
                self._dispatch_image_load(index, path, size, plugin, cancel)
        else:
            self._dispatch_resolve(index, path, size, cancel)

    def _dispatch_resolve(self, index, path, size, cancel):
        def task():
            if cancel.is_cancelled():
                return
            plugin = None
            for plugin_cls in grid_resolver.resolve_chain(path):
                if not plugin_cls.can_handle(path):
                    continue
                plugin = grid_resolver.registry.instance(plugin_cls.NAME)
                break
            if cancel.is_cancelled():
                return
            if plugin is None:
                self._load_image(index, path, size, grid_resolver.load, cancel)
                return
            if isinstance(plugin, _WidgetGridPlugin):
                self._thumb_dispatcher.invoke(
                    lambda: self._on_resolve_widget(index, path, size, plugin, cancel)
                )
            else:
                self._load_image(index, path, size, plugin.load, cancel)

        self._render_dispatcher.post(task, priority=100, cancel=cancel)

    def _on_resolve_widget(self, index, path, size, plugin, cancel):
        if cancel.is_cancelled() or index not in self._active:
            return
        self._promote_fn(index, plugin.NAME)
        widget = self._widget_lookup(index)
        if widget is not None:
            plugin.render(widget, path, size)
        if plugin.REQUIRE_THUMBNAIL:
            self._dispatch_thumbnail(index, path, size, plugin, cancel)

    def _dispatch_widget_render(self, index, path, size, plugin, cancel):
        widget = self._widget_lookup(index)
        if widget is not None:
            plugin.render(widget, path, size)
        if plugin.REQUIRE_THUMBNAIL:
            self._dispatch_thumbnail(index, path, size, plugin, cancel)

    def _dispatch_image_load(self, index, path, size, plugin, cancel):
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
            lambda: self._load_image(index, path, size, plugin.load, cancel),
            priority=plugin.PRIORITY, cancel=cancel,
        )

    def _load_image(self, index, path, size, load_fn, cancel):
        fkey = fullsize_key(path)
        cached = self._cache.get_if_sufficient(fkey, size)
        if cached is None:
            cached = self._cache.get_if_sufficient(path, size)
        if cached is not None:
            self._image_ready.emit(index, path, cached)
            return
        image = load_fn(path, size)
        if cancel.is_cancelled():
            return
        if image is None or (isinstance(image, QtGui.QImage) and image.isNull()):
            image = _get_error_image(size)
        self._cache[path] = image
        self._image_ready.emit(index, path, image)

    def _dispatch_thumbnail(self, index, path, size, plugin, cancel):
        def task():
            if cancel.is_cancelled():
                return
            cached = self._cache.get_if_sufficient(fullsize_key(path), size)
            if cached is None:
                cached = self._cache.get_if_sufficient(path, size)
            if cached is not None:
                self._thumb_dispatcher.invoke(
                    lambda: self._deliver_thumbnail(index, plugin, cached)
                )
                return
            image = grid_resolver.load(path, size)
            if image is None or cancel.is_cancelled():
                return
            self._cache[path] = image
            self._thumb_dispatcher.invoke(
                lambda: self._deliver_thumbnail(index, plugin, image)
            )
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
