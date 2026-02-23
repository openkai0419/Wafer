from abc import abstractmethod
from ..registry import BasePlugin


class BaseViewerPlugin(BasePlugin):

    def create_widget(self, parent=None):
        return None

    @abstractmethod
    def load_content(self, path: str):
        ...

    def clear(self, widget):
        pass
