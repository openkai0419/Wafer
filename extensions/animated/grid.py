import os

from PySide6 import QtCore, QtGui

from wafer.plugin import WidgetGridPlugin
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


_DEFAULT_DELAY = 100
_MIN_DELAY = 20


def _decode_frames(path: str, size: QtCore.QSize | None, job) -> tuple[list[QtGui.QPixmap], list[int]]:
    reader = QtGui.QImageReader(path)
    reader.setAutoTransform(True)
    pixmaps: list[QtGui.QPixmap] = []
    delays: list[int] = []
    count = reader.imageCount()
    if count <= 0:
        count = 1024
    for i in range(count):
        if job.is_cancelled():
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
    EXTENSIONS = ('.gif', '.apng', '.webp', '.png')
    PRIORITY = 200
    WIDGET_CLASS = AnimatedCellWidget
    REQUIRE_THUMBNAIL = True

    @classmethod
    @profiler.profile
    def can_handle(cls, path: str) -> bool:
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

    @profiler.profile
    def render(self, job):
        cached = _frame_cache.get_if_sufficient(job.path, job.size)
        if cached is not None:
            frames, delays = cached
            job.invoke(lambda w: w.set_frames(job.path, frames, delays))
            return
        job.post(lambda: self._decode_and_set(job), priority=0)

    @staticmethod
    def _decode_and_set(job):
        frames, delays = _decode_frames(job.path, job.size, job)
        if job.is_cancelled() or not frames:
            return
        _frame_cache.put(job.path, frames, delays)
        job.invoke(lambda w: w.set_frames(job.path, frames, delays))

    @profiler.profile
    def on_thumb_loaded(self, widget, image):
        widget.set_thumbnail(image)

    @profiler.profile
    def release(self, widget):
        widget.suspend()

    @profiler.profile
    def appear(self, widget):
        widget.on_appeared()

    @profiler.profile
    def disappear(self, widget):
        widget.on_disappeared()

    @profiler.profile
    def select(self, widget):
        widget.on_selected()

    @profiler.profile
    def deselect(self, widget):
        widget.on_deselected()
