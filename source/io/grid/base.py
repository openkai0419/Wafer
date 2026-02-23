from abc import abstractmethod
from ..registry import BasePlugin


class BaseGridPlugin(BasePlugin):
    WIDGET_CLASS = None

    @abstractmethod
    def load(self, path: str, size=None):
        ...

    def render(self, path, widget, size=None):
        pass
