from afterimages.plugin import WidgetGridPlugin
from .widget import MpvCellWidget


class VideoGridPlugin(WidgetGridPlugin):
    NAME = 'video'
    EXTENSIONS = (
        '.mp4', '.mkv', '.webm', '.avi', '.mov',
        '.wmv', '.flv', '.m4v', '.ts', '.mpg', '.mpeg',
    )
    PRIORITY = 100
    WIDGET_CLASS = MpvCellWidget

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

    def render(self, widget, path, size=None):
        widget.load(path, size)

    def release(self, widget):
        widget.suspend()

    def appear(self, widget):
        widget.on_selected()

    def disappear(self, widget):
        widget.on_deselected()

    def select(self, widget):
        widget.on_selected()

    def deselect(self, widget):
        widget.on_deselected()
