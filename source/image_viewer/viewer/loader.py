from ...common.funcs import uipx
from ...common.profiling import profiler
from ...io.grid import load as grid_load
from ...qt.thread import AdaptiveThreadPool
from PySide6 import QtCore, QtGui, QtWidgets

class ImageLoaderSignal(QtCore.QObject):
    image_ready = QtCore.Signal(int, object)
    widget_ready = QtCore.Signal(int, object, object)


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

        cache_key = (self.path, self.size.width(), self.size.height())
        image = self.receiver.image_cache.get(cache_key)

        if self._cancelled:
                return
        
        if image is None:
            image = grid_load(self.path, self.size)

        if image is None:
            image = self.get_error_image()

        if self._cancelled:
            return
        if isinstance(image, QtGui.QImage):
            if image.isNull():
                image = self.get_error_image()
            self.receiver.image_cache[cache_key] = image
            self.signal.image_ready.emit(self.index, image)
        
        if isinstance(image, list):
            if issubclass(image[0], QtWidgets.QWidget):
                self.signal.widget_ready.emit(self.index, image[0], image[1])


        
