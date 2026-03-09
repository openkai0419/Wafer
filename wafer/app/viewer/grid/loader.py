from ....utils.formatting import dpix
from ....utils.profiling import profiler
from ....plugin.grid.handler import grid_resolver
from ....core.qt.thread import AdaptiveThreadPool
from ..grid.cachemanager import fullsize_key
from PySide6 import QtCore, QtGui


class ImageLoaderSignal(QtCore.QObject):
    image_ready = QtCore.Signal(int, object)


class ImageLoaderRunnable(QtCore.QRunnable):

    @profiler.profile
    def __init__(self, index, path, cell_size, grid_view):
        super().__init__()
        self.index = index
        self.path = path
        margin = dpix(3)
        self.size = cell_size - QtCore.QSize(margin * 2, margin * 2)
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

        cache = self.grid_view.image_cache
        cached = cache.peek_if_sufficient(fullsize_key(self.path), self.size)
        if cached is None:
            cached = cache.peek_if_sufficient(self.path, self.size)
        if cached is not None:
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
