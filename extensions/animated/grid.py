import os

from wafer.plugin import WidgetGridPlugin
from wafer.utils.profiling import profiler
from .widget import AnimatedCellWidget

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
    def render(self, widget, path, size=None):
        widget.load(path, size)

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
