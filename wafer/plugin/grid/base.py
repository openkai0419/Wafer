from abc import ABC, abstractmethod
from ..registry import BasePlugin


class BaseGridPlugin(BasePlugin, ABC):
    pass


class ImageGridPlugin(BaseGridPlugin):

    @abstractmethod
    def load(self, path: str, size=None):
        ...


class WidgetGridPlugin(BaseGridPlugin):
    WIDGET_CLASS = None
    REQUIRE_THUMBNAIL = False

    def render(self, widget, path, size=None):
        pass

    def on_thumb_loaded(self, widget, image):
        pass

    def release(self, widget):
        pass

    def appear(self, widget):
        pass

    def disappear(self, widget):
        pass

    def select(self, widget):
        pass

    def deselect(self, widget):
        pass
