from wafer.plugin import WidgetViewerPlugin
from .viewer_widget import VideoViewerWidget, DEFAULT_VOLUME


class VideoViewerPlugin(WidgetViewerPlugin):
    NAME = "video"
    EXTENSIONS = (
        ".mp4",
        ".mkv",
        ".webm",
        ".avi",
        ".mov",
        ".wmv",
        ".flv",
        ".m4v",
        ".ts",
        ".mpg",
        ".mpeg",
    )
    PRIORITY = 100
    DEFAULT_ENABLED = True
    WIDGET_CLASS = VideoViewerWidget

    def render(self, path):
        self.widget.load(path)

    def clear(self):
        self.widget.clear()

    def activate(self):
        self.widget.activate()

    def deactivate(self):
        self.widget.deactivate()

    def set_autoplay(self, advance):
        self.widget.set_autoplay_advance(advance)
        return advance is not None

    def save_state(self):
        return {
            "volume": self.widget._volume,
            "muted": self.widget._muted,
            "speed": self.widget._speed,
            "fit_mode": self.widget._cover_mode,
            "loop": self.widget._looping,
            "pause_in_background": self.widget._pause_in_background,
        }

    def restore_state(self, state):
        self.widget.set_volume(state.get("volume", DEFAULT_VOLUME))
        self.widget.set_muted(state.get("muted", False))
        self.widget.set_speed(state.get("speed", 1.0))
        self.widget.set_cover_mode(state.get("fit_mode", False))
        self.widget.set_looping(state.get("loop", False))
        self.widget.set_pause_in_background(state.get("pause_in_background", False))
