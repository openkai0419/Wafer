from wafer.plugin import WidgetViewerPlugin
from ._common import is_animated
from .viewer_widget import AnimatedViewerWidget


class AnimatedViewerPlugin(WidgetViewerPlugin):
    NAME = 'animated'
    EXTENSIONS = ('.gif', '.apng', '.webp')
    PRIORITY = 200
    WIDGET_CLASS = AnimatedViewerWidget

    @classmethod
    def can_handle(cls, path: str) -> bool:
        return is_animated(path)

    def render(self, widget, path):
        widget.load(path)

    def clear(self, widget):
        widget.clear()

    def activate(self, widget):
        widget.activate()

    def deactivate(self, widget):
        widget.deactivate()

    def save_state(self, widget):
        return {
            'fit_mode': widget._cover_mode,
        }

    def restore_state(self, widget, state):
        widget.set_cover_mode(state.get('fit_mode', False))
