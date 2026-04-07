from wafer.plugin import WidgetViewerPlugin
from ._common import is_animated
from .viewer_widget import AnimatedViewerWidget


class AnimatedViewerPlugin(WidgetViewerPlugin):
    NAME = "animated"
    EXTENSIONS = (".gif", ".apng", ".webp")
    PRIORITY = 200
    WIDGET_CLASS = AnimatedViewerWidget
    DEFAULT_ENABLED = True

    @classmethod
    def can_handle(cls, path: str) -> bool:
        return is_animated(path)

    def render(self, path):
        self.widget.load(path)

    def clear(self):
        self.widget.clear()

    def activate(self):
        self.widget.activate()

    def deactivate(self):
        self.widget.deactivate()

    def save_state(self):
        return {
            "fit_mode": self.widget._cover_mode,
        }

    def restore_state(self, state):
        self.widget.set_cover_mode(state.get("fit_mode", False))
