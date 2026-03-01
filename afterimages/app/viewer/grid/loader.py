from afterimages.utils.formatting import dpix
from afterimages.utils.profiling import profiler
from afterimages.plugin.grid.handler import grid_resolver
from afterimages.core.qt.thread import AdaptiveThreadPool
from ..grid.cachemanager import fullsize_key
from PySide6 import QtCore, QtGui


class ImageLoaderSignal(QtCore.QObject):
    image_ready = QtCore.Signal(int, object)


class ImageLoaderRunnable(QtCore.QRunnable):

    @profiler.profile
    def __init__(self, index, path, size, grid_view):
        super().__init__()
        self.index = index
        self.path = path
        self.margin = dpix(3)
        self.size = size - QtCore.QSize(self.margin * 2, self.margin * 2)
        self.grid_view = grid_view
        self._cancelled = False
        self.signal = ImageLoaderSignal()

    def cancel(self):
        self._cancelled = True

    def get_error_image(self):
        return self.grid_view.error_placeholder.scaled(
            self.size,
            QtCore.Qt.IgnoreAspectRatio,
            QtCore.Qt.SmoothTransformation
        )

    @AdaptiveThreadPool.register(30, 1000)
    def run(self):
        if self._cancelled:
            return

        cached = self.grid_view.image_cache.peek(fullsize_key(self.path))
        if cached is None:
            cached = self.grid_view.image_cache.peek(self.path)
        if cached is not None and cached.width() >= self.size.width() and cached.height() >= self.size.height():
            if not self._cancelled:
                self.signal.image_ready.emit(self.index, cached)
            return

        if self._cancelled:
            return

        image = grid_resolver.load(self.path, self.size)

        if image is None:
            image = self.get_error_image()

        if self._cancelled:
            return

        if isinstance(image, QtGui.QImage):
            if image.isNull():
                image = self.get_error_image()
            self.signal.image_ready.emit(self.index, image)
