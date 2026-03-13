from wafer.plugin import WidgetGridPlugin
from wafer.utils.profiling import profiler
from .widget import MpvCellWidget


class VideoGridPlugin(WidgetGridPlugin):
    NAME = 'video'
    EXTENSIONS = (
        '.mp4', '.mkv', '.webm', '.avi', '.mov',
        '.wmv', '.flv', '.m4v', '.ts', '.mpg', '.mpeg',
    )
    PRIORITY = 100
    WIDGET_CLASS = MpvCellWidget
    REQUIRE_THUMBNAIL = True

    @classmethod
    def post_install(cls, plugin_dir, on_progress=None):
        from ._downloader import ensure_mpv_dll
        ensure_mpv_dll()

    @classmethod
    def configure(cls):
        from PySide6.QtGui import QSurfaceFormat
        fmt = QSurfaceFormat()
        fmt.setSwapBehavior(QSurfaceFormat.SwapBehavior.DoubleBuffer)
        QSurfaceFormat.setDefaultFormat(fmt)

    @profiler.profile
    def render(self, widget, path, size):
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
