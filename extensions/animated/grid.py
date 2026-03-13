import os
from functools import lru_cache

from PySide6 import QtCore, QtGui

from wafer.plugin import WidgetGridPlugin
from wafer.core.qt.dispatcher import Dispatcher
from wafer.utils.profiling import profiler
from .widget import AnimatedCellWidget, _frame_cache

_PNG_SIGNATURE_LEN = 8
_CHUNK_HEADER_LEN = 8
_CHUNK_CRC_LEN = 4
_HEADER_READ_SIZE = 4096


def _has_actl_chunk(header: bytes) -> bool:
    offset = _PNG_SIGNATURE_LEN
    while offset + _CHUNK_HEADER_LEN <= len(header):
        chunk_len = int.from_bytes(header[offset:offset + 4], 'big')
        chunk_type = header[offset + 4:offset + _CHUNK_HEADER_LEN]
        if chunk_type == b'acTL':
            return True
        if chunk_type == b'IDAT':
            return False
        offset += _CHUNK_HEADER_LEN + chunk_len + _CHUNK_CRC_LEN
    return False


def _is_animated_webp(header: bytes) -> bool:
    if len(header) < 12 or header[:4] != b'RIFF' or header[8:12] != b'WEBP':
        return False
    offset = 12
    while offset + 8 <= len(header):
        fourcc = header[offset:offset + 4]
        size = int.from_bytes(header[offset + 4:offset + 8], 'little')
        if fourcc == b'ANIM':
            return True
        offset += 8 + size + (size % 2)
    return False


def _is_animated_gif(header: bytes) -> bool:
    return b'NETSCAPE2.0' in header or b'ANIMEXTS1.0' in header


@lru_cache(maxsize=8192)
def _is_animated(path: str) -> bool:
    ext = os.path.splitext(path)[1].lower()
    if ext == '.apng':
        return True
    try:
        with open(path, 'rb') as f:
            header = f.read(_HEADER_READ_SIZE)
    except OSError:
        return False
    if ext == '.png':
        return _has_actl_chunk(header)
    if ext == '.webp':
        return _is_animated_webp(header)
    if ext == '.gif':
        return _is_animated_gif(header)
    return False


_DEFAULT_DELAY = 100
_MIN_DELAY = 20


def _decode_frames(path: str, size: QtCore.QSize | None, is_stale) -> tuple[list[QtGui.QPixmap], list[int]]:
    reader = QtGui.QImageReader(path)
    reader.setAutoTransform(True)
    pixmaps: list[QtGui.QPixmap] = []
    delays: list[int] = []
    count = reader.imageCount()
    if count <= 0:
        count = 1024
    for i in range(count):
        if is_stale():
            return [], []
        delay = reader.nextImageDelay()
        if delay < _MIN_DELAY:
            delay = _DEFAULT_DELAY
        image = reader.read()
        if image.isNull():
            break
        if size is not None and image.size() != size:
            image = image.scaled(
                size, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        pixmaps.append(QtGui.QPixmap.fromImage(image))
        delays.append(delay)
    return pixmaps, delays


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
        return _is_animated(path)

    @profiler.profile
    def render(self, widget, path, size):
        cached = _frame_cache.get_if_sufficient(path, size)
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
        frames, delays = _decode_frames(path, size, is_stale)
        if cancel.is_cancelled() or widget._path != path or not frames:
            return
        _frame_cache.put(path, frames, delays)
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
