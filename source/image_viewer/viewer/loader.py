from ...common.funcs import uipx
from ...common.profiling import profiler
from ...io.manager import LoaderClass

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

    def run(self):
        if self._cancelled:
            return

        cache_key = (self.path, self.size.width(), self.size.height())
        image = self.receiver.image_cache.get(cache_key)

        if image is None:
            if self._cancelled:
                return
            image = LoaderClass.load(self.path, self.size)

            if image is None or image.isNull():
                image = self.receiver.error_placeholder.scaled(
                    self.size,
                    QtCore.Qt.IgnoreAspectRatio,
                    QtCore.Qt.SmoothTransformation
                )

            self.receiver.image_cache[cache_key] = image

        if self._cancelled:
            return

        QtCore.QMetaObject.invokeMethod(
            self.receiver,
            '_on_image_ready',
            QtCore.Qt.QueuedConnection,
            QtCore.Q_ARG(int, self.index),
            QtCore.Q_ARG(QtGui.QImage, image)
        )
