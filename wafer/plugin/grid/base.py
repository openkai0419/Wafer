from abc import ABC
from typing import Any
from PySide6 import QtCore
from ..registry import BasePlugin

_error_image_cache = None


def _get_error_image(size):
    global _error_image_cache
    if _error_image_cache is None:
        from ...core.qt.pixmap import PixmapFactory

        _error_image_cache = PixmapFactory.create_error_placeholder().toImage()
    return _error_image_cache.scaled(
        size,
        QtCore.Qt.IgnoreAspectRatio,
        QtCore.Qt.SmoothTransformation,
    )


class BaseGridPlugin(BasePlugin, ABC):
    pass


class WidgetGridPlugin(BaseGridPlugin):
    WIDGET_CLASS = None
    REQUIRE_THUMBNAIL = False

    def render(self, widget, path, size):
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

    def save_state(self) -> dict[str, Any]:
        return {}

    def restore_state(self, state: dict[str, Any]) -> None:
        pass
