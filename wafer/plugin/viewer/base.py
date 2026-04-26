from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any
from ..registry import BasePlugin


class BaseViewerPlugin(BasePlugin, ABC):
    pass


class ImageViewerPlugin(BaseViewerPlugin):
    @abstractmethod
    def load_content(self, path: str): ...


class WidgetViewerPlugin(BaseViewerPlugin):
    WIDGET_CLASS = None

    def __init__(self):
        self.widget = self.WIDGET_CLASS() if self.WIDGET_CLASS else None

    def render(self, path):
        pass

    def clear(self):
        pass

    def activate(self):
        pass

    def deactivate(self):
        pass

    def set_autoplay(self, advance: Callable[[], None] | None) -> bool:
        return False

    def save_ui_state(self) -> dict[str, Any]:
        return {}

    def restore_ui_state(self, state: dict[str, Any]) -> None:
        pass
