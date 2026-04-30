from PySide6 import QtCore, QtGui, QtWidgets

from wafer.core.commands.bridge import ActionKit, UI
from wafer.core.qt.dispatcher import Dispatcher, CancelSlot
from wafer.core.qt.thread import utility_pool
from ._common import decode_frames, get_viewer_driver, _viewer_cache


class AnimatedViewerWidget(QtWidgets.QWidget, ActionKit.UIMixin):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: black;")
        self._path: str = ""
        self._frames: list[QtGui.QPixmap] = []
        self._delays: list[int] = []
        self._frame_index = 0
        self._accumulated = 0
        self._playing = False
        self.cover_mode = False
        self._scaled_pixmap: QtGui.QPixmap | None = None
        self._scaled_key: tuple = ()
        self._cancel = CancelSlot()
        self._dispatcher = Dispatcher(utility_pool)
        self.init_command_binding("AnimatedView")
        UI.register_instance("AnimatedViewerWidget", self)

    def extend_context(self, ctx, cmd, event=None, key=None, source=None):
        from wafer.utils.virtual_paths import physical_path
        p = self._path
        s = physical_path(p) if p else None
        return {"path": p, "paths": [p] if p else [], "source": s, "sources": [s] if s else []}

    def load(self, path: str):
        self._cancel.cancel()
        self.stop()
        self._path = path
        self._frames = []
        self._delays = []
        self._frame_index = 0
        self._accumulated = 0
        self._scaled_pixmap = None
        self._scaled_key = ()

        cached = _viewer_cache.get(path)
        if cached is not None:
            frames, delays = cached
            self._set_frames(frames, delays)
            return

        cancel = self._cancel.renew()
        self._dispatcher.post(lambda: self._decode(path, cancel), cancel=cancel)

    def _decode(self, path, cancel):
        def is_stale():
            return cancel.is_cancelled() or self._path != path

        frames, delays = decode_frames(path, None, is_stale)
        if cancel.is_cancelled() or self._path != path or not frames:
            return
        _viewer_cache.put(path, frames, delays)
        self._dispatcher.invoke(lambda: self._on_decoded(path, frames, delays))

    def _on_decoded(self, path, frames, delays):
        if self._path != path:
            return
        self._set_frames(frames, delays)

    def _set_frames(self, frames, delays):
        self._frames = frames
        self._delays = delays
        self._frame_index = 0
        self._accumulated = 0
        self._scaled_pixmap = None
        self._scaled_key = ()
        self.update()
        if len(frames) > 1:
            self.start()

    def start(self):
        if self._playing or len(self._frames) <= 1:
            return
        self._playing = True
        self._accumulated = 0
        get_viewer_driver().register(self)

    def stop(self):
        if not self._playing:
            return
        self._playing = False
        get_viewer_driver().unregister(self)

    def clear(self):
        self._cancel.cancel()
        self.stop()
        self._path = ""
        self._frames = []
        self._delays = []
        self._frame_index = 0
        self._accumulated = 0
        self._scaled_pixmap = None
        self._scaled_key = ()
        self.update()

    def activate(self):
        if self._frames and len(self._frames) > 1:
            self.start()

    def deactivate(self):
        self.stop()

    def set_cover_mode(self, cover: bool):
        self.cover_mode = cover
        self._scaled_pixmap = None
        self._scaled_key = ()
        self.update()

    def toggle_fit_mode(self):
        self.set_cover_mode(not self.cover_mode)

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

    def paintEvent(self, event):
        if not self._frames:
            return
        pixmap = self._frames[self._frame_index]
        if pixmap is None:
            return
        pw, ph = pixmap.width(), pixmap.height()
        ww, wh = self.width(), self.height()
        if pw <= 0 or ph <= 0 or ww <= 0 or wh <= 0:
            return
        key = (id(pixmap), ww, wh, self.cover_mode)
        if key != self._scaled_key:
            sx, sy = ww / pw, wh / ph
            scale = max(sx, sy) if self.cover_mode else min(sx, sy)
            dw, dh = int(pw * scale), int(ph * scale)
            self._scaled_pixmap = pixmap.scaled(dw, dh, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
            self._scaled_key = key
        scaled = self._scaled_pixmap
        painter = QtGui.QPainter(self)
        x = (ww - scaled.width()) // 2
        y = (wh - scaled.height()) // 2
        if self.cover_mode:
            painter.setClipRect(0, 0, ww, wh)
        painter.drawPixmap(x, y, scaled)
