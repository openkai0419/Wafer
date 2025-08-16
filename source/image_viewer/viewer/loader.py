from ...common.funcs import uipx
from ...common.profiling import profiler
from ...io.image_reader import ImageLoader

from PySide6 import QtCore, QtGui

class ImageLoaderRunnable(QtCore.QRunnable):
    def __init__(self, index, path, size, receiver):
        super().__init__()
        self.index = index
        self.path = path
        self.margin = uipx(3)
        self.size = size - QtCore.QSize(self.margin * 2, self.margin * 2)
        self.receiver = receiver
        self._cancelled = False
        self.isended = False

    def cancel(self):
        self._cancelled = True

    @profiler.profile
    def run(self):
        if self._cancelled:
            return

        cache_key = (self.path, self.size.width(), self.size.height())
        pixmap = self.receiver.pixmap_cache.get(cache_key)

        if pixmap is None:
            if self._cancelled:
                return
            if ImageLoader.is_loadable(self.path):
                pixmap = ImageLoader(self.path).load(self.size)

            if pixmap is None or pixmap.isNull():
                pixmap = self.receiver.error_placeholder.scaled(
                    self.size,
                    QtCore.Qt.IgnoreAspectRatio,
                    QtCore.Qt.SmoothTransformation
                )

            self.receiver.pixmap_cache[cache_key] = pixmap

        if self._cancelled:
            return

        QtCore.QMetaObject.invokeMethod(
            self.receiver,
            '_on_pixmap_ready',
            QtCore.Qt.QueuedConnection,
            QtCore.Q_ARG(int, self.index),
            QtCore.Q_ARG(QtGui.QPixmap, pixmap)
        )