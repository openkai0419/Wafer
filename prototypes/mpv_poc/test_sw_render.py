import os
import sys
import time
import ctypes

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.environ['PATH'] = SCRIPT_DIR + os.pathsep + os.environ.get('PATH', '')
if hasattr(os, 'add_dll_directory'):
    os.add_dll_directory(SCRIPT_DIR)

import mpv

from PySide6 import QtCore, QtWidgets, QtGui
from PySide6.QtCore import Qt, Signal, Slot


PREVIEW_W = 1920
PREVIEW_H = 1080


class _MpvSwSize(ctypes.Structure):
    _fields_ = [('w', ctypes.c_int), ('h', ctypes.c_int)]


class _MpvSwStride(ctypes.Structure):
    _fields_ = [('stride', ctypes.c_size_t)]


mpv.MpvRenderParam.TYPES['sw_size'] = (17, _MpvSwSize)
mpv.MpvRenderParam.TYPES['sw_format'] = (18, str)
mpv.MpvRenderParam.TYPES['sw_stride'] = (19, _MpvSwStride)
mpv.MpvRenderParam.TYPES['sw_pointer'] = (20, ctypes.c_void_p)


class SwRenderViewer(QtWidgets.QWidget):

    _update_signal = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle('Approach B: SW Render API (api_type=sw)')
        self.resize(800, 500)
        self.setStyleSheet('background: #111;')

        self._label = QtWidgets.QLabel()
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setMinimumSize(320, 240)

        self._info = QtWidgets.QLabel()
        self._info.setFixedHeight(40)
        self._info.setStyleSheet(
            'color: #0f0; background: #1a1a1a; padding: 2px 8px; '
            'font: bold 11px Consolas;'
        )

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._label, 1)
        layout.addWidget(self._info)

        self._render_w = PREVIEW_W
        self._render_h = PREVIEW_H
        self._stride = self._render_w * 4
        self._buf_size = self._stride * self._render_h
        self._buf = (ctypes.c_uint8 * self._buf_size)()
        self._buf_ptr = ctypes.cast(self._buf, ctypes.c_void_p)

        self.player = mpv.MPV(
            vo='libmpv',
            hwdec='auto',
            keep_open='yes',
            idle='yes',
        )

        self._ctx: mpv.MpvRenderContext | None = None
        try:
            self._ctx = mpv.MpvRenderContext(self.player, 'sw')
            self._ctx.update_cb = self._on_mpv_update
            self._info.setText('SW render context created OK')
        except Exception as e:
            self._info.setText(f'SW render init failed: {e}')

        self._update_signal.connect(self._render_frame, Qt.ConnectionType.QueuedConnection)

        self._frame_count = 0
        self._fps = 0
        self._t_render = 0.0
        self._t_convert = 0.0
        self._t_display = 0.0
        self._fps_clock = QtCore.QTimer(self, interval=1000)
        self._fps_clock.timeout.connect(self._tick_fps)
        self._fps_clock.start()

    def _on_mpv_update(self):
        self._update_signal.emit()

    @Slot()
    def _render_frame(self):
        if self._ctx is None:
            return
        t0 = time.perf_counter()
        try:
            self._ctx.render(
                sw_size={'w': self._render_w, 'h': self._render_h},
                sw_format='0bgr',
                sw_stride={'stride': self._stride},
                sw_pointer=self._buf_ptr,
            )
        except Exception as e:
            self._info.setText(f'Render error: {type(e).__name__}: {e}')
            return
        t1 = time.perf_counter()

        qimg = QtGui.QImage(
            bytes(self._buf[:self._buf_size]),
            self._render_w, self._render_h, self._stride,
            QtGui.QImage.Format.Format_RGB32,
        )
        t2 = time.perf_counter()

        self._label.setPixmap(QtGui.QPixmap.fromImage(qimg))
        t3 = time.perf_counter()

        self._frame_count += 1
        self._t_render = (t1 - t0) * 1000
        self._t_convert = (t2 - t1) * 1000
        self._t_display = (t3 - t2) * 1000

    def _tick_fps(self):
        self._fps = self._frame_count
        self._frame_count = 0
        pos = self.player.time_pos
        dur = self.player.duration
        ts = f'{pos:.1f}/{dur:.1f}s' if pos and dur else '--'
        total = self._t_render + self._t_convert + self._t_display
        self._info.setText(
            f'FPS: {self._fps} | {self._render_w}x{self._render_h} | '
            f'Total: {total:.1f}ms\n'
            f'  render: {self._t_render:.1f}ms | '
            f'copy: {self._t_convert:.1f}ms | '
            f'display: {self._t_display:.1f}ms'
        )

    def load(self, path):
        self.player.play(path)

    def resizeEvent(self, event):
        super().resizeEvent(event)

    def closeEvent(self, event):
        if self._ctx:
            self._ctx.free()
            self._ctx = None
        self.player.terminate()
        super().closeEvent(event)


def main():
    app = QtWidgets.QApplication(sys.argv)
    win = SwRenderViewer()
    win.show()
    path = sys.argv[1] if len(sys.argv) > 1 else None
    if not path:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            win, 'Open Video', '',
            'Video (*.mp4 *.mkv *.webm *.avi *.mov);;All (*)',
        )
    if path:
        win.load(path)
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
