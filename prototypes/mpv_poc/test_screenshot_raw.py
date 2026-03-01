import os
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.environ['PATH'] = SCRIPT_DIR + os.pathsep + os.environ.get('PATH', '')
if hasattr(os, 'add_dll_directory'):
    os.add_dll_directory(SCRIPT_DIR)

import mpv

from PySide6 import QtCore, QtWidgets, QtGui
from PySide6.QtCore import Qt


PREVIEW_W = 480
PREVIEW_H = 270


class ScreenshotRawViewer(QtWidgets.QWidget):

    TARGET_FPS = 30

    def __init__(self):
        super().__init__()
        self.setWindowTitle('Approach A: screenshot-raw (vo=null)')
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

        self.player = mpv.MPV(
            vo='null',
            hwdec='auto',
            keep_open='yes',
            idle='yes',
            vf=f'scale={PREVIEW_W}:{PREVIEW_H}',
        )

        self._grab_timer = QtCore.QTimer(self)
        self._grab_timer.setInterval(1000 // self.TARGET_FPS)
        self._grab_timer.timeout.connect(self._grab_frame)

        self._frame_count = 0
        self._fps = 0.0
        self._t_capture = 0.0
        self._t_convert = 0.0
        self._t_display = 0.0
        self._res_text = ''
        self._fps_clock = QtCore.QTimer(self, interval=1000)
        self._fps_clock.timeout.connect(self._tick_fps)

    def load(self, path):
        self.player.play(path)
        self._grab_timer.start()
        self._fps_clock.start()

    def _grab_frame(self):
        try:
            t0 = time.perf_counter()
            res = self.player.command('screenshot-raw', 'video')
            t1 = time.perf_counter()
            if res is None:
                return
            w, h, stride = res['w'], res['h'], res['stride']
            self._res_text = f'{w}x{h}'
            qimg = QtGui.QImage(
                res['data'], w, h, stride,
                QtGui.QImage.Format.Format_RGB32,
            ).copy()
            t2 = time.perf_counter()
            self._label.setPixmap(QtGui.QPixmap.fromImage(qimg))
            t3 = time.perf_counter()
            self._frame_count += 1
            self._t_capture = (t1 - t0) * 1000
            self._t_convert = (t2 - t1) * 1000
            self._t_display = (t3 - t2) * 1000
        except mpv.MpvError:
            pass
        except Exception as e:
            self._info.setText(f'Error: {type(e).__name__}: {e}')

    def _tick_fps(self):
        self._fps = self._frame_count
        self._frame_count = 0
        pos = self.player.time_pos
        dur = self.player.duration
        ts = f'{pos:.1f}/{dur:.1f}s' if pos and dur else '--'
        total = self._t_capture + self._t_convert + self._t_display
        self._info.setText(
            f'FPS: {self._fps}/{self.TARGET_FPS} | {self._res_text} | '
            f'Total: {total:.1f}ms\n'
            f'  capture: {self._t_capture:.1f}ms | '
            f'copy: {self._t_convert:.1f}ms | '
            f'display: {self._t_display:.1f}ms'
        )

    def closeEvent(self, event):
        self._grab_timer.stop()
        self._fps_clock.stop()
        self.player.terminate()
        super().closeEvent(event)


def main():
    app = QtWidgets.QApplication(sys.argv)
    win = ScreenshotRawViewer()
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
