from abc import ABC, abstractmethod
from typing import Any
from ..registry import BasePlugin


class BaseViewerPlugin(BasePlugin, ABC):
    pass


class ImageViewerPlugin(BaseViewerPlugin):

    @abstractmethod
    def load_content(self, path: str):
        ...


class WidgetViewerPlugin(BaseViewerPlugin):
    WIDGET_CLASS = None

    def render(self, widget, path):
        pass

    def clear(self, widget):
        pass

    def save_state(self, widget) -> dict[str, Any]:
        return {}

    def restore_state(self, widget, state: dict[str, Any]) -> None:
        pass
