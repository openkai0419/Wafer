import os

from wafer.plugin import WidgetGridPlugin
from wafer.utils.profiling import profiler
from .widget import AnimatedCellWidget

_ACTL_CHUNK = b'acTL'
_WEBP_ANIM_CHUNK = b'ANIM'
_GIF_NETSCAPE = b'NETSCAPE2.0'
_GIF_ANIMEXTS = b'ANIMEXTS1.0'
_HEADER_READ_SIZE = 4096


class AnimatedGridPlugin(WidgetGridPlugin):
    NAME = 'animated'
    EXTENSIONS = ('.gif', '.apng', '.webp', '.png')
    PRIORITY = 200
    WIDGET_CLASS = AnimatedCellWidget
    REQUIRE_THUMBNAIL = True

    @classmethod
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
            return _ACTL_CHUNK in header
        if ext == '.webp':
            return _WEBP_ANIM_CHUNK in header
        if ext == '.gif':
            return _GIF_NETSCAPE in header or _GIF_ANIMEXTS in header
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
