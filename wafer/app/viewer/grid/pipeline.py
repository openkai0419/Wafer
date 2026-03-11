from typing import Callable, Optional

from PySide6 import QtCore, QtGui

from ....core.qt.dispatcher import Dispatcher, CancelToken
from ....plugin.grid.cell_job import CellJob
from ....plugin.grid.handler import grid_resolver
from ....plugin.grid.base import WidgetGridPlugin as _WidgetGridPlugin, _get_error_image
from .calc_layout import JustifiedLayoutCalculator, MasonryLayoutCalculator, LayoutData
from .cachemanager import fullsize_key


def _load_widget_thumbnail(plugin, job, cancel, thumb_dispatcher):
    def task():
        if cancel.is_set():
            return
        cached = job.image_cache.get(fullsize_key(job.path))
        if cached is None:
            cached = job.image_cache.get(job.path)
        if cached is not None:
            job.invoke(lambda w: plugin.on_thumb_loaded(w, cached))
            return
        image = grid_resolver.load(job.path, job.size)
        if image is None or cancel.is_set():
            return
        job.image_cache[job.path] = image
        job.invoke(lambda w: plugin.on_thumb_loaded(w, image))
    thumb_dispatcher.post(task, priority=5, cancel=cancel)


def _make_fallback_task(job, cancel):
    def task():
        if cancel.is_set():
            return
        cached = job.image_cache.get_if_sufficient(fullsize_key(job.path), job.size)
        if cached is None:
            cached = job.image_cache.get_if_sufficient(job.path, job.size)
        if cached is not None:
            job.invoke(lambda item: item.set_image(cached, job.path))
            return
        image = grid_resolver.load(job.path, job.size)
        if cancel.is_set():
            return
        if image is None or (isinstance(image, QtGui.QImage) and image.isNull()):
            image = _get_error_image(job.size)
        job.image_cache[job.path] = image
        job.invoke(lambda item: item.set_image(image, job.path))
    return task


def _execute_plugin_render(plugin, job, cancel, thumb_dispatcher):
    if cancel.is_set():
        return
    if not isinstance(plugin, _WidgetGridPlugin):
        fkey = fullsize_key(job.path)
        cached = job.image_cache.get_if_sufficient(fkey, job.size)
        if cached is not None:
            job.invoke(lambda item: item.set_image(cached, job.path))
            return
    plugin.render(job)
    if isinstance(plugin, _WidgetGridPlugin) and plugin.REQUIRE_THUMBNAIL and not cancel.is_set():
        _load_widget_thumbnail(plugin, job, cancel, thumb_dispatcher)


def _make_resolve_task(job, cancel, promote_fn, thumb_dispatcher):
    def task():
        if cancel.is_set():
            return
        plugin = None
        for plugin_cls in grid_resolver.resolve_chain(job.path):
            if not plugin_cls.can_handle(job.path):
                continue
            plugin = grid_resolver.registry.instance(plugin_cls.NAME)
            break
        if cancel.is_set():
            return
        if plugin is None:
            _make_fallback_task(job, cancel)()
            return
        if isinstance(plugin, _WidgetGridPlugin):
            name = plugin.NAME
            job.invoke_raw(lambda: promote_fn(job.index, name))
        _execute_plugin_render(plugin, job, cancel, thumb_dispatcher)
    return task


class GridPipeline(QtCore.QObject):
    layout_ready = QtCore.Signal(object)

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
        self._layout_cancel: CancelToken | None = None

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
        if self._layout_cancel is not None:
            self._layout_cancel.set()
        cancel = CancelToken()
        self._layout_cancel = cancel

        def task():
            if cancel.is_set():
                return
            if layout_mode == 'masonry':
                calc = MasonryLayoutCalculator(
                    aspect_ratios, base_height, spacing,
                    container_width, container_height, orientation,
                )
            else:
                calc = JustifiedLayoutCalculator(
                    aspect_ratios, base_height, spacing,
                    container_width, container_height, orientation,
                )
            calc.run()
            if cancel.is_set():
                return
            layout = calc._result
            if layout is not None:
                self._utility_dispatcher.invoke(lambda: self.layout_ready.emit(layout))

        self._utility_dispatcher.post(task, priority=7, cancel=cancel)

    def schedule_render(self, index: int, path: str, size: QtCore.QSize, plugin=None):
        self.cancel_index(index)

        cancel = CancelToken()
        self._active[index] = cancel

        job = CellJob(
            index=index,
            path=path,
            size=size,
            image_cache=self._cache,
            cancel=cancel,
            dispatcher=self._thumb_dispatcher,
            widget_lookup=self._widget_lookup,
            render_dispatcher=self._render_dispatcher,
        )

        if plugin is not None:
            def make_task(p=plugin, j=job, c=cancel, td=self._thumb_dispatcher):
                def task():
                    _execute_plugin_render(p, j, c, td)
                return task

            self._render_dispatcher.post(make_task(), priority=plugin.PRIORITY, cancel=cancel)
        else:
            self._render_dispatcher.post(
                _make_resolve_task(job, cancel, self._promote_fn, self._thumb_dispatcher),
                priority=100, cancel=cancel,
            )

    def cancel_index(self, index: int):
        token = self._active.pop(index, None)
        if token is not None:
            token.set()

    def cancel_all(self):
        if self._layout_cancel is not None:
            self._layout_cancel.set()
            self._layout_cancel = None
        for token in self._active.values():
            token.set()
        self._active.clear()

    def active_count(self) -> int:
        return len(self._active)
