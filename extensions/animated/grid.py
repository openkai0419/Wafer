from PySide6 import QtCore, QtGui

from wafer.plugin import WidgetGridPlugin
from wafer.core.qt.dispatcher import Dispatcher
from wafer.utils.profiling import profiler
from ._common import is_animated, decode_frames, _grid_cache
from .widget import AnimatedCellWidget


class AnimatedGridPlugin(WidgetGridPlugin):
    NAME = 'animated'
    EXTENSIONS = ('.gif', '.apng', '.webp')
    PRIORITY = 200
    WIDGET_CLASS = AnimatedCellWidget
    REQUIRE_THUMBNAIL = True

    def __init__(self):
        super().__init__()
        from wafer.core.qt.thread import grid_render_pool
        self._dispatcher = Dispatcher(grid_render_pool)

    @classmethod
    @profiler.profile
    def can_handle(cls, path: str) -> bool:
        return is_animated(path)

    @profiler.profile
    def render(self, widget, path, size):
        cached = _grid_cache.get_if_sufficient(path, size)
        if cached is not None:
            frames, delays = cached
            widget.set_frames(path, frames, delays)
            return
        cancel = widget._cancel_slot.renew()
        widget._path = path
        self._dispatcher.post(
            lambda: self._decode_and_set(widget, path, size, cancel),
            priority=0, cancel=cancel)

    def _decode_and_set(self, widget, path, size, cancel):
        def is_stale():
            return cancel.is_cancelled() or widget._path != path
        frames, delays = decode_frames(path, size, is_stale)
        if cancel.is_cancelled() or widget._path != path or not frames:
            return
        _grid_cache.put(path, frames, delays)
        self._dispatcher.invoke(
            lambda: widget.set_frames(path, frames, delays) if widget._path == path else None)

    @profiler.profile
    def on_thumb_loaded(self, widget, image):
        widget.set_thumbnail(image)

    @profiler.profile
    def release(self, widget):
        widget._cancel_slot.cancel()
        widget.suspend()

    @profiler.profile
    def appear(self, widget):
        widget.on_appeared()

    @profiler.profile
    def disappear(self, widget):
        widget.on_disappeared()
