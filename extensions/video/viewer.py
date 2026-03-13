from wafer.plugin import WidgetViewerPlugin
from .viewer_widget import VideoViewerWidget, DEFAULT_VOLUME


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

    def save_state(self, widget):
        return {
            'volume': widget._volume,
            'muted': widget._muted,
            'speed': widget._speed,
            'fit_mode': widget._cover_mode,
            'loop': widget._looping,
        }

    def restore_state(self, widget, state):
        widget.set_volume(state.get('volume', DEFAULT_VOLUME))
        muted = state.get('muted', False)
        if muted != widget._muted:
            widget.toggle_mute()
        widget.set_speed(state.get('speed', 1.0))
        if state.get('fit_mode', False) != widget._cover_mode:
            widget.toggle_fit_mode()
        if state.get('loop', False) != widget._looping:
            widget.toggle_loop()
