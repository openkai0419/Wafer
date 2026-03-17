import os
import threading
from collections import OrderedDict
from functools import lru_cache

from PySide6 import QtCore, QtGui

from wafer.utils.profiling import profiler

_PNG_SIGNATURE_LEN = 8
_CHUNK_HEADER_LEN = 8
_CHUNK_CRC_LEN = 4
_HEADER_READ_SIZE = 4096


def _has_actl_chunk(header: bytes) -> bool:
    offset = _PNG_SIGNATURE_LEN
    while offset + _CHUNK_HEADER_LEN <= len(header):
        chunk_len = int.from_bytes(header[offset:offset + 4], 'big')
        chunk_type = header[offset + 4:offset + _CHUNK_HEADER_LEN]
        if chunk_type == b'acTL':
            return True
        if chunk_type == b'IDAT':
            return False
        offset += _CHUNK_HEADER_LEN + chunk_len + _CHUNK_CRC_LEN
    return False


def _is_animated_webp(header: bytes) -> bool:
    if len(header) < 12 or header[:4] != b'RIFF' or header[8:12] != b'WEBP':
        return False
    offset = 12
    while offset + 8 <= len(header):
        fourcc = header[offset:offset + 4]
        size = int.from_bytes(header[offset + 4:offset + 8], 'little')
        if fourcc == b'ANIM':
            return True
        offset += 8 + size + (size % 2)
    return False


def _is_animated_gif(header: bytes) -> bool:
    return b'NETSCAPE2.0' in header or b'ANIMEXTS1.0' in header


@lru_cache(maxsize=8192)
def is_animated(path: str) -> bool:
    ext = os.path.splitext(path)[1].lower()
    if ext == '.apng':
        return True
    try:
        with open(path, 'rb') as f:
            header = f.read(_HEADER_READ_SIZE)
    except OSError:
        return False
    if ext == '.png':
        return _has_actl_chunk(header)
    if ext == '.webp':
        return _is_animated_webp(header)
    if ext == '.gif':
        return _is_animated_gif(header)
    return False


_MIN_DELAY = 4


def decode_frames(path: str, size: QtCore.QSize | None, is_stale) -> tuple[list[QtGui.QPixmap], list[int]]:
    reader = QtGui.QImageReader(path)
    reader.setAutoTransform(True)
    pixmaps: list[QtGui.QPixmap] = []
    delays: list[int] = []
    count = reader.imageCount()
    if count <= 0:
        count = 1024
    for i in range(count):
        if is_stale():
            return [], []
        image = reader.read()
        if image.isNull():
            break
        delay = reader.nextImageDelay()
        if delay < _MIN_DELAY:
            delay = _MIN_DELAY
        if size is not None and image.size() != size:
            image = image.scaled(
                size, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        pixmaps.append(QtGui.QPixmap.fromImage(image))
        delays.append(delay)
    return pixmaps, delays


class FrameCache:

    def __init__(self, max_entries=128):
        self._max = max_entries
        self._cache: OrderedDict[str, tuple[list[QtGui.QPixmap], list[int]]] = OrderedDict()
        self._lock = threading.Lock()

    @profiler.profile
    def get(self, path: str) -> tuple[list[QtGui.QPixmap], list[int]] | None:
        with self._lock:
            entry = self._cache.get(path)
            if entry is not None:
                self._cache.move_to_end(path)
            return entry

    @profiler.profile
    def get_if_sufficient(self, path: str, size: QtCore.QSize) -> tuple[list[QtGui.QPixmap], list[int]] | None:
        with self._lock:
            entry = self._cache.get(path)
            if entry is None:
                return None
            frames, delays = entry
            if frames:
                first = frames[0]
                if first.width() < size.width() or first.height() < size.height():
                    self._cache.pop(path)
                    return None
            self._cache.move_to_end(path)
            return entry

    @profiler.profile
    def put(self, path: str, frames: list[QtGui.QPixmap], delays: list[int]):
        with self._lock:
            if path in self._cache:
                self._cache.pop(path)
            elif len(self._cache) >= self._max:
                self._cache.popitem(last=False)
            self._cache[path] = (frames, delays)

    def __contains__(self, path: str) -> bool:
        with self._lock:
            return path in self._cache

    def remove(self, path: str):
        with self._lock:
            self._cache.pop(path, None)

    def clear(self):
        with self._lock:
            self._cache.clear()


class AnimationDriver(QtCore.QObject):

    frame_advanced = QtCore.Signal()

    def __init__(self, interval=33, parent=None):
        super().__init__(parent)
        self._timer = QtCore.QTimer(self)
        self._timer.setTimerType(QtCore.Qt.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._cells: set = set()
        self._interval = interval
        self._clock = QtCore.QElapsedTimer()
        self._last_ms = 0

    def register(self, cell):
        self._cells.add(cell)
        if not self._timer.isActive():
            self._clock.start()
            self._last_ms = 0
            self._timer.start(self._interval)

    def unregister(self, cell):
        self._cells.discard(cell)
        if not self._cells and self._timer.isActive():
            self._timer.stop()

    def _tick(self):
        now = self._clock.elapsed()
        delta = now - self._last_ms
        self._last_ms = now
        for cell in list(self._cells):
            cell.advance(delta)
        self.frame_advanced.emit()


_driver: AnimationDriver | None = None
_viewer_driver: AnimationDriver | None = None
_grid_cache = FrameCache()
_viewer_cache = FrameCache(max_entries=8)


def get_driver() -> AnimationDriver:
    global _driver
    if _driver is None:
        _driver = AnimationDriver()
    return _driver


def get_viewer_driver() -> AnimationDriver:
    global _viewer_driver
    if _viewer_driver is None:
        _viewer_driver = AnimationDriver(interval=16)
    return _viewer_driver
