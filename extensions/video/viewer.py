from wafer.plugin import WidgetViewerPlugin
from .viewer_widget import VideoViewerWidget


class VideoViewerPlugin(WidgetViewerPlugin):
    NAME = 'video'
    EXTENSIONS = (
        '.mp4', '.mkv', '.webm', '.avi', '.mov',
        '.wmv', '.flv', '.m4v', '.ts', '.mpg', '.mpeg',
    )
    PRIORITY = 100
    WIDGET_CLASS = VideoViewerWidget

    def render(self, widget, path):
        widget.load(path)

    def clear(self, widget):
        widget.clear()
