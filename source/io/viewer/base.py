from abc import abstractmethod
from ..registry import BasePlugin


class BaseViewerPlugin(BasePlugin):
    WIDGET_CLASS = None

    @abstractmethod
    def load_content(self, path: str):
        ...

    def render(self, path, widget):
        pass

    def clear(self, widget):
        pass
