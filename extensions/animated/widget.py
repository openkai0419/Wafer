from PySide6 import QtCore, QtGui, QtWidgets

from wafer.core.qt.dispatcher import CancelSlot
from wafer.utils.profiling import profiler
from ._common import FrameCache, AnimationDriver, get_driver, _grid_cache

_DISPOSE_INTERVAL = 16
_DISPOSE_BATCH = 8


class _PixmapDisposer:

    def __init__(self):
        self._queue: list[QtGui.QPixmap] = []
        self._timer: QtCore.QTimer | None = None

    def schedule(self, pixmaps: list[QtGui.QPixmap]):
        if not pixmaps:
            return
        self._queue.extend(pixmaps)
        if self._timer is None:
            self._timer = QtCore.QTimer()
            self._timer.timeout.connect(self._flush)
        if not self._timer.isActive():
            self._timer.start(_DISPOSE_INTERVAL)

    def _flush(self):
        for _ in range(_DISPOSE_BATCH):
            if not self._queue:
                break
            self._queue.pop()
        if not self._queue and self._timer is not None:
            self._timer.stop()


_disposer = _PixmapDisposer()


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
        self._cancel_slot = CancelSlot()

    @profiler.profile
    def set_frames(self, path: str, frames: list[QtGui.QPixmap], delays: list[int]):
        self._path = path
        self._frames = frames
        self._delays = delays
        self._frame_index = 0
        self._accumulated = 0
        if frames:
            self._thumbnail = frames[0]
        if self.isVisible():
            self.update()
            if len(frames) > 1:
                self.start()

    @profiler.profile
    def set_thumbnail(self, image):
        if self._thumbnail is not None:
            return
        self._thumbnail = QtGui.QPixmap.fromImage(image) if isinstance(image, QtGui.QImage) else image
        if self.isVisible():
            self.update()

    def start(self):
        if self._playing or len(self._frames) <= 1:
            return
        self._playing = True
        self._accumulated = 0
        get_driver().register(self)

    def stop(self):
        if not self._playing:
            return
        self._playing = False
        get_driver().unregister(self)

    @profiler.profile
    def suspend(self):
        self.stop()
        path = self._path
        frames = self._frames
        thumbnail = self._thumbnail
        self._frames = []
        self._delays = []
        self._thumbnail = None
        self._path = ''
        self._frame_index = 0
        self._accumulated = 0
        to_dispose: list[QtGui.QPixmap] = []
        if frames and (not path or path not in _grid_cache):
            to_dispose.extend(frames)
        elif thumbnail is not None:
            to_dispose.append(thumbnail)
        if to_dispose:
            _disposer.schedule(to_dispose)

    def advance(self, delta_ms: int):
        if not self._frames or not self._delays:
            return
        self._accumulated += delta_ms
        changed = False
        while self._accumulated >= self._delays[self._frame_index]:
            self._accumulated -= self._delays[self._frame_index]
            self._frame_index = (self._frame_index + 1) % len(self._frames)
            changed = True
        if changed:
            self.update()

    @profiler.profile
    def on_appeared(self):
        self.start()

    @profiler.profile
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
        pw, ph = pixmap.width(), pixmap.height()
        ww, wh = self.width(), self.height()
        if pw <= 0 or ph <= 0 or ww <= 0 or wh <= 0:
            return
        painter = QtGui.QPainter(self)
        if pw == ww and ph == wh:
            painter.drawPixmap(0, 0, pixmap)
        else:
            scale = max(ww / pw, wh / ph)
            src_w = ww / scale
            src_h = wh / scale
            sx = (pw - src_w) / 2
            sy = (ph - src_h) / 2
            painter.drawPixmap(
                QtCore.QRectF(0, 0, ww, wh),
                pixmap,
                QtCore.QRectF(sx, sy, src_w, src_h),
            )
