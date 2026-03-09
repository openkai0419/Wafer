from PySide6 import QtCore, QtGui, QtWidgets

from wafer.utils.profiling import profiler


class FrameCache:

    def __init__(self, max_entries=128):
        self._max = max_entries
        self._cache: dict[str, tuple[list[QtGui.QPixmap], list[int]]] = {}
        self._order: list[str] = []

    def get(self, path: str) -> tuple[list[QtGui.QPixmap], list[int]] | None:
        entry = self._cache.get(path)
        if entry is not None:
            self._order.remove(path)
            self._order.append(path)
        return entry

    def get_if_sufficient(self, path: str, size: QtCore.QSize) -> tuple[list[QtGui.QPixmap], list[int]] | None:
        entry = self._cache.get(path)
        if entry is None:
            return None
        frames, delays = entry
        if frames:
            first = frames[0]
            if first.width() < size.width() or first.height() < size.height():
                del self._cache[path]
                self._order.remove(path)
                return None
        self._order.remove(path)
        self._order.append(path)
        return entry

    def put(self, path: str, frames: list[QtGui.QPixmap], delays: list[int]):
        if path in self._cache:
            self._order.remove(path)
        elif len(self._cache) >= self._max:
            evict = self._order.pop(0)
            del self._cache[evict]
        self._cache[path] = (frames, delays)
        self._order.append(path)

    def remove(self, path: str):
        if path in self._cache:
            del self._cache[path]
            self._order.remove(path)

    def clear(self):
        self._cache.clear()
        self._order.clear()


_DEFAULT_DELAY = 100
_MIN_DELAY = 20


class _DecodeSignals(QtCore.QObject):
    ready = QtCore.Signal(str, list, list)


class _DecodeRunner(QtCore.QRunnable):
    def __init__(self, path: str, size: QtCore.QSize | None):
        super().__init__()
        self.path = path
        self.size = size
        self.signals = _DecodeSignals()
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        if self._cancelled:
            return
        reader = QtGui.QImageReader(self.path)
        reader.setAutoTransform(True)
        images: list[QtGui.QImage] = []
        delays: list[int] = []
        count = reader.imageCount()
        if count <= 0:
            count = 1024
        for i in range(count):
            if self._cancelled:
                return
            delay = reader.nextImageDelay()
            if delay < _MIN_DELAY:
                delay = _DEFAULT_DELAY
            image = reader.read()
            if image.isNull():
                break
            if self.size is not None and image.size() != self.size:
                image = image.scaled(
                    self.size, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
            images.append(image)
            delays.append(delay)
        if not self._cancelled:
            self.signals.ready.emit(self.path, images, delays)


_thread_pool: QtCore.QThreadPool | None = None


def _get_thread_pool() -> QtCore.QThreadPool:
    global _thread_pool
    if _thread_pool is None:
        _thread_pool = QtCore.QThreadPool()
        _thread_pool.setMaxThreadCount(2)
    return _thread_pool


class AnimationDriver(QtCore.QObject):

    frame_advanced = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._timer = QtCore.QTimer(self)
        self._timer.setTimerType(QtCore.Qt.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._cells: set['AnimatedCellWidget'] = set()
        self._elapsed = 0
        self._interval = 33

    def register(self, cell: 'AnimatedCellWidget'):
        self._cells.add(cell)
        if not self._timer.isActive():
            self._elapsed = 0
            self._timer.start(self._interval)

    def unregister(self, cell: 'AnimatedCellWidget'):
        self._cells.discard(cell)
        if not self._cells and self._timer.isActive():
            self._timer.stop()

    def _tick(self):
        self._elapsed += self._interval
        for cell in list(self._cells):
            cell.advance(self._elapsed)
        self.frame_advanced.emit()


_driver: AnimationDriver | None = None
_frame_cache = FrameCache()


def _get_driver() -> AnimationDriver:
    global _driver
    if _driver is None:
        _driver = AnimationDriver()
    return _driver


class AnimatedCellWidget(QtWidgets.QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._path: str = ''
        self._frames: list[QtGui.QPixmap] = []
        self._delays: list[int] = []
        self._frame_index = 0
        self._accumulated = 0
        self._playing = False
        self._thumbnail: QtGui.QPixmap | None = None
        self._decode_runner: _DecodeRunner | None = None

    @profiler.profile
    def load(self, path: str, size: QtCore.QSize | None = None):
        self._path = path
        self._frame_index = 0
        self._accumulated = 0
        self._cancel_runners()
        if size is not None:
            cached = _frame_cache.get_if_sufficient(path, size)
        else:
            cached = _frame_cache.get(path)
        if cached is not None:
            self._frames, self._delays = cached
            self._thumbnail = self._frames[0] if self._frames else None
            self.update()
            return
        self._frames = []
        self._delays = []
        self._thumbnail = None
        pool = _get_thread_pool()
        decode = _DecodeRunner(path, size)
        decode.signals.ready.connect(
            self._on_decode_ready, QtCore.Qt.ConnectionType.QueuedConnection)
        self._decode_runner = decode
        pool.start(decode)

    def set_thumbnail(self, image):
        if self._thumbnail is not None:
            return
        self._thumbnail = QtGui.QPixmap.fromImage(image) if isinstance(image, QtGui.QImage) else image
        self.update()

    def _cancel_runners(self):
        if self._decode_runner is not None:
            self._decode_runner.cancel()
            self._decode_runner = None

    @QtCore.Slot(str, list, list)
    @profiler.profile
    def _on_decode_ready(self, path: str, images: list[QtGui.QImage], delays: list[int]):
        if path != self._path:
            return
        self._decode_runner = None
        frames = [QtGui.QPixmap.fromImage(img) for img in images]
        self._frames = frames
        self._delays = delays
        if frames:
            self._thumbnail = frames[0]
            _frame_cache.put(path, frames, delays)
        self.update()
        if self.isVisible() and len(self._frames) > 1:
            self.start()

    def start(self):
        if self._playing or len(self._frames) <= 1:
            return
        self._playing = True
        self._accumulated = 0
        _get_driver().register(self)

    def stop(self):
        if not self._playing:
            return
        self._playing = False
        _get_driver().unregister(self)

    def suspend(self):
        self.stop()
        self._cancel_runners()
        self._frames = []
        self._delays = []
        self._thumbnail = None
        self._path = ''
        self._frame_index = 0
        self._accumulated = 0

    def advance(self, elapsed_ms: int):
        if not self._frames or not self._delays:
            return
        self._accumulated += _get_driver()._interval
        delay = self._delays[self._frame_index]
        if self._accumulated >= delay:
            self._accumulated -= delay
            self._frame_index = (self._frame_index + 1) % len(self._frames)
            self.update()

    def on_appeared(self):
        self.start()

    def on_disappeared(self):
        self.stop()

    def on_selected(self):
        pass

    def on_deselected(self):
        pass

    def paintEvent(self, event):
        if not self._frames:
            pixmap = self._thumbnail
        else:
            pixmap = self._frames[self._frame_index]
        if pixmap is None:
            return
        painter = QtGui.QPainter(self)
        pw, ph = pixmap.width(), pixmap.height()
        ww, wh = self.width(), self.height()
        if pw <= 0 or ph <= 0 or ww <= 0 or wh <= 0:
            return
        scale = min(ww / pw, wh / ph)
        dw, dh = int(pw * scale), int(ph * scale)
        x = (ww - dw) // 2
        y = (wh - dh) // 2
        painter.drawPixmap(x, y, dw, dh, pixmap)
