import os
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.environ['PATH'] = SCRIPT_DIR + os.pathsep + os.environ.get('PATH', '')
if hasattr(os, 'add_dll_directory'):
    os.add_dll_directory(SCRIPT_DIR)

import mpv
from PySide6 import QtCore, QtWidgets, QtGui


class MpvCell(QtWidgets.QWidget):

    QUALITY_PRESETS = {
        'full': {},
        'medium': {
            'vf': 'scale=480:-1,fps=24',
            'vd_lavc_skiploopfilter': 'nonref',
        },
        'low': {
            'vf': 'scale=100:-1,fps=24',
            'vd_lavc_skiploopfilter': 'all',
            'vd_lavc_skipframe': 'nonref',
            'framedrop': 'vo',
            'vd_lavc_threads': '1',
        },
        'minimal': {
            'vf': 'scale=160:-1,fps=10',
            'vd_lavc_skiploopfilter': 'all',
            'vd_lavc_skipframe': 'bidir',
            'framedrop': 'vo',
            'vd_lavc_threads': '1',
        },
    }

    def __init__(self, index, parent=None):
        super().__init__(parent)
        self.index = index
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_NativeWindow, True)
        self.setMinimumSize(160, 120)
        self.setStyleSheet('background-color: black;')
        self.player = None
        self._path = None

    def start(self, path, mute=True, volume=50, quality='full'):
        self._path = path
        preset = self.QUALITY_PRESETS.get(quality, {})

        opts = {
            'wid': str(int(self.winId())),
            'vo': 'gpu',
            'hwdec': 'auto',
            'keep_open': 'yes',
            'loop': 'inf',
        }
        opts.update(preset)

        self.player = mpv.MPV(**opts)
        self.player.mute = mute
        self.player.volume = volume
        self.player.play(path)

    def stop(self):
        if self.player:
            self.player.terminate()
            self.player = None

    def closeEvent(self, event):
        self.stop()
        super().closeEvent(event)


class MultiPlayWindow(QtWidgets.QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle('mpv Multi-Play Benchmark')
        self.resize(1200, 800)
        self._cells = []
        self._video_paths = []

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root = QtWidgets.QVBoxLayout(central)

        toolbar = QtWidgets.QHBoxLayout()
        root.addLayout(toolbar)

        btn_folder = QtWidgets.QPushButton('Select Folder')
        btn_folder.clicked.connect(self._select_folder)
        toolbar.addWidget(btn_folder)

        toolbar.addWidget(QtWidgets.QLabel('Count:'))
        self._count_spin = QtWidgets.QSpinBox()
        self._count_spin.setRange(1, 64)
        self._count_spin.setValue(4)
        toolbar.addWidget(self._count_spin)

        toolbar.addWidget(QtWidgets.QLabel('Cols:'))
        self._cols_spin = QtWidgets.QSpinBox()
        self._cols_spin.setRange(1, 16)
        self._cols_spin.setValue(2)
        toolbar.addWidget(self._cols_spin)

        self._mute_chk = QtWidgets.QCheckBox('Mute All')
        self._mute_chk.setChecked(True)
        toolbar.addWidget(self._mute_chk)

        toolbar.addWidget(QtWidgets.QLabel('Quality:'))
        self._quality_combo = QtWidgets.QComboBox()
        for name in MpvCell.QUALITY_PRESETS:
            self._quality_combo.addItem(name)
        self._quality_combo.setCurrentText('full')
        toolbar.addWidget(self._quality_combo)

        btn_start = QtWidgets.QPushButton('Start')
        btn_start.clicked.connect(self._start_all)
        toolbar.addWidget(btn_start)

        btn_stop = QtWidgets.QPushButton('Stop All')
        btn_stop.clicked.connect(self._stop_all)
        toolbar.addWidget(btn_stop)

        toolbar.addStretch()

        self._status = QtWidgets.QLabel('Select a folder with video files')
        toolbar.addWidget(self._status)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        root.addWidget(scroll, 1)

        self._grid_container = QtWidgets.QWidget()
        self._grid_layout = QtWidgets.QGridLayout(self._grid_container)
        self._grid_layout.setSpacing(2)
        scroll.setWidget(self._grid_container)

    def _select_folder(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, 'Select Video Folder')
        if not folder:
            return
        video_exts = {'.mp4', '.mkv', '.webm', '.avi', '.mov', '.wmv', '.flv'}
        self._video_paths = sorted(
            os.path.join(folder, f) for f in os.listdir(folder)
            if os.path.splitext(f)[1].lower() in video_exts
        )
        self._status.setText(f'{len(self._video_paths)} videos found in {os.path.basename(folder)}')

    def _stop_all(self):
        for cell in self._cells:
            cell.stop()
        for i in reversed(range(self._grid_layout.count())):
            w = self._grid_layout.itemAt(i).widget()
            if w:
                self._grid_layout.removeWidget(w)
                w.setParent(None)
                w.deleteLater()
        self._cells.clear()
        self._status.setText('Stopped')

    def _start_all(self):
        if not self._video_paths:
            self._status.setText('No videos. Select a folder first.')
            return

        self._stop_all()

        count = self._count_spin.value()
        cols = self._cols_spin.value()
        mute = self._mute_chk.isChecked()
        quality = self._quality_combo.currentText()

        t0 = time.perf_counter()
        for i in range(count):
            cell = MpvCell(i)
            r, c = divmod(i, cols)
            self._grid_layout.addWidget(cell, r, c)
            self._cells.append(cell)

        QtWidgets.QApplication.processEvents()

        for i, cell in enumerate(self._cells):
            path = self._video_paths[i % len(self._video_paths)]
            cell.start(path, mute=mute, quality=quality)

        elapsed = time.perf_counter() - t0
        self._status.setText(
            f'{count} players started in {elapsed:.2f}s '
            f'(quality={quality}, mute={mute})'
        )

    def closeEvent(self, event):
        self._stop_all()
        super().closeEvent(event)


def main():
    app = QtWidgets.QApplication(sys.argv)
    win = MultiPlayWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
