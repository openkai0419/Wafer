from abc import ABC, abstractmethod
from PySide6 import QtCore, QtGui
from ..registry import BasePlugin

_error_image_cache = None


def _get_error_image(size):
    global _error_image_cache
    if _error_image_cache is None:
        from ...core.qt.pixmap import PixmapFactory
        _error_image_cache = PixmapFactory.create_error_placeholder().toImage()
    return _error_image_cache.scaled(
        size, QtCore.Qt.IgnoreAspectRatio, QtCore.Qt.SmoothTransformation,
    )


class BaseGridPlugin(BasePlugin, ABC):
    pass


class ImageGridPlugin(BaseGridPlugin):

    @abstractmethod
    def load(self, path: str, size=None):
        ...

    def render(self, job):
        cached = job.image_cache.get_if_sufficient(job.path, job.size)
        if cached is not None:
            job.invoke(lambda item: item.set_image(cached, job.path))
            return
        image = self.load(job.path, job.size)
        if job.is_cancelled():
            return
        if image is None or (isinstance(image, QtGui.QImage) and image.isNull()):
            image = _get_error_image(job.size)
        job.image_cache[job.path] = image
        job.invoke(lambda item: item.set_image(image, job.path))


class WidgetGridPlugin(BaseGridPlugin):
    WIDGET_CLASS = None
    REQUIRE_THUMBNAIL = False

    def render(self, job):
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
