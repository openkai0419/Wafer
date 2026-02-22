from abc import abstractmethod
from ..registry import BasePlugin


class BaseGridPlugin(BasePlugin):

    @abstractmethod
    def load(self, path: str, size=None):
        ...

    def create_cell_widget(self, parent=None):
        return None
