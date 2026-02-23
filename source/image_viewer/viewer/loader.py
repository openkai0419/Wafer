from ...common.funcs import uipx
from ...common.profiling import profiler
from ...io.grid.handler import grid_handler
from ...qt.thread import AdaptiveThreadPool
from ..viewer.cachemanager import fullsize_key
from PySide6 import QtCore, QtGui


class ImageLoaderSignal(QtCore.QObject):
    image_ready = QtCore.Signal(int, object)
    widget_ready = QtCore.Signal(int, str)


class ImageLoaderRunnable(QtCore.QRunnable):

    @profiler.profile
    def __init__(self, index, path, size, receiver):
        super().__init__()
        self.index = index
        self.path = path
        self.margin = uipx(3)
        self.size = size - QtCore.QSize(self.margin * 2, self.margin * 2)
        self.receiver = receiver
        self._cancelled = False
        self.isended = False
        self.signal = ImageLoaderSignal()

    def cancel(self):
        self._cancelled = True

    def get_error_image(self):
        return self.receiver.error_placeholder.scaled(
            self.size,
            QtCore.Qt.IgnoreAspectRatio,
            QtCore.Qt.SmoothTransformation
        )

    @AdaptiveThreadPool.register(30, 1000)
    def run(self):
        if self._cancelled:
            return

        plugin_cls = grid_handler.resolve(self.path)
        if plugin_cls is not None and plugin_cls.WIDGET_CLASS is not None:
            if not self._cancelled:
                self.signal.widget_ready.emit(self.index, plugin_cls.NAME)
            return

        cached = self.receiver.image_cache.peek(fullsize_key(self.path))
        if cached is None:
            cached = self.receiver.image_cache.peek(self.path)
        if cached is not None and cached.width() >= self.size.width() and cached.height() >= self.size.height():
            if not self._cancelled:
                self.signal.image_ready.emit(self.index, cached)
            return

        if self._cancelled:
            return

        image = grid_handler.load(self.path, self.size)

        if image is None:
            image = self.get_error_image()

        if self._cancelled:
            return

        if isinstance(image, QtGui.QImage):
            if image.isNull():
                image = self.get_error_image()
            self.signal.image_ready.emit(self.index, image)
