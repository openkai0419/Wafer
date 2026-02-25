import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.environ['PATH'] = SCRIPT_DIR + os.pathsep + os.environ.get('PATH', '')
if hasattr(os, 'add_dll_directory'):
    os.add_dll_directory(SCRIPT_DIR)

import mpv
from PySide6 import QtCore, QtWidgets, QtGui


class MpvWidget(QtWidgets.QWidget):

    file_started = QtCore.Signal(str)
    file_ended = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_NativeWindow, True)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setMinimumSize(320, 240)
        self.setStyleSheet('background-color: black;')
        self._playlist = []
        self._playlist_index = -1
        self._loop = False
        self._auto_play = True
        self._transitioning = False
        self._volume = 100
        self._mute = False
        self._speed = 1.0
        self._panscan = 0.0
        self.player = None

    def _create_player(self):
        self.player = mpv.MPV(
            wid=str(int(self.winId())),
            vo='gpu',
            hwdec='auto',
            keep_open='yes',
            idle='yes',
            log_handler=self._log_handler,
        )
        self.player.volume = self._volume
        self.player.mute = self._mute
        self.player.speed = self._speed
        self.player['panscan'] = self._panscan
        self.player.observe_property('eof-reached', self._on_eof_reached)

        @self.player.event_callback('end-file')
        def _on_end(event):
            QtCore.QMetaObject.invokeMethod(
                self, '_handle_end_file',
                QtCore.Qt.ConnectionType.QueuedConnection,
            )

    def _ensure_player(self):
        if self.player is None:
            self._create_player()

    def _on_eof_reached(self, _name, value):
        if value:
            QtCore.QMetaObject.invokeMethod(
                self, '_handle_eof',
                QtCore.Qt.ConnectionType.QueuedConnection,
            )

    def _log_handler(self, loglevel, component, message):
        if loglevel in ('error', 'fatal'):
            print(f'[mpv/{loglevel}] {component}: {message}')

    @property
    def _current_path(self):
        if self._playlist and 0 <= self._playlist_index < len(self._playlist):
            return self._playlist[self._playlist_index]
        return ''

    @QtCore.Slot()
    def _handle_eof(self):
        if self._transitioning:
            return
        self.file_ended.emit(self._current_path)
        if self._loop:
            self._replay_current()
        elif self._auto_play and len(self._playlist) > 1:
            self._advance_playlist()

    @QtCore.Slot()
    def _handle_end_file(self):
        if self._transitioning:
            self._transitioning = False

    def _replay_current(self):
        self._transitioning = True
        if self.player is not None:
            self.player.seek(0, reference='absolute')
            self.player.pause = False

    def _advance_playlist(self):
        self._playlist_index = (self._playlist_index + 1) % len(self._playlist)
        self._play_current()

    def _play_current(self):
        if not self._playlist or self._playlist_index < 0:
            return
        self._ensure_player()
        self._transitioning = True
        self.player.play(self._current_path)
        self.player.pause = False
        self.file_started.emit(self._current_path)

    def load(self, path):
        self._playlist = [path]
        self._playlist_index = 0
        self._play_current()

    def set_playlist(self, paths, start_index=0):
        self._playlist = list(paths)
        self._playlist_index = min(start_index, len(paths) - 1) if paths else -1
        if self._playlist:
            self._play_current()

    def play_index(self, index):
        if 0 <= index < len(self._playlist):
            self._playlist_index = index
            self._play_current()

    def next_in_playlist(self):
        if not self._playlist:
            return
        self._playlist_index = (self._playlist_index + 1) % len(self._playlist)
        self._play_current()

    def prev_in_playlist(self):
        if not self._playlist:
            return
        self._playlist_index = (self._playlist_index - 1) % len(self._playlist)
        self._play_current()

    def set_loop(self, enabled):
        self._loop = enabled

    def set_auto_play(self, enabled):
        self._auto_play = enabled

    def toggle_pause(self):
        if self.player is not None:
            self.player.pause = not self.player.pause

    def stop(self):
        if self.player is not None:
            self._transitioning = True
            self.player.terminate()
            self.player = None

    def set_volume(self, vol):
        self._volume = vol
        if self.player is not None:
            self.player.volume = vol

    def set_mute(self, mute):
        self._mute = mute
        if self.player is not None:
            self.player.mute = mute

    def seek(self, seconds):
        if self.player is not None:
            self.player.seek(seconds)

    def seek_absolute(self, seconds):
        if self.player is not None:
            self.player.seek(seconds, reference='absolute')

    def frame_step(self):
        if self.player is not None:
            self.player.frame_step()

    def frame_back_step(self):
        if self.player is not None:
            self.player.frame_back_step()

    def set_speed(self, speed):
        self._speed = speed
        if self.player is not None:
            self.player.speed = speed

    def set_fit_mode(self, cover):
        self._panscan = 1.0 if cover else 0.0
        if self.player is not None:
            self.player['panscan'] = self._panscan

    @property
    def duration(self):
        return self.player.duration if self.player is not None else None

    @property
    def time_pos(self):
        return self.player.time_pos if self.player is not None else None

    def closeEvent(self, event):
        if self.player is not None:
            self._transitioning = True
            self.player.terminate()
            self.player = None
        super().closeEvent(event)


class TestWindow(QtWidgets.QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle('mpv PySide6 Embed Test (F2=toggle controls)')
        self.resize(1000, 650)

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root = QtWidgets.QHBoxLayout(central)

        left = QtWidgets.QVBoxLayout()
        root.addLayout(left, 1)

        self.mpv_widget = MpvWidget()
        left.addWidget(self.mpv_widget, 1)

        self._toggle_widgets = []

        controls = QtWidgets.QHBoxLayout()
        left.addLayout(controls)

        btn_open = QtWidgets.QPushButton('Open')
        btn_open.clicked.connect(self._open_file)
        controls.addWidget(btn_open)

        btn_pause = QtWidgets.QPushButton('Play/Pause')
        btn_pause.clicked.connect(self.mpv_widget.toggle_pause)
        controls.addWidget(btn_pause)

        btn_stop = QtWidgets.QPushButton('Stop')
        btn_stop.clicked.connect(self.mpv_widget.stop)
        controls.addWidget(btn_stop)

        btn_prev = QtWidgets.QPushButton('|<<')
        btn_prev.clicked.connect(self.mpv_widget.prev_in_playlist)
        controls.addWidget(btn_prev)

        btn_next = QtWidgets.QPushButton('>>|')
        btn_next.clicked.connect(self.mpv_widget.next_in_playlist)
        controls.addWidget(btn_next)

        self._btn_loop = QtWidgets.QPushButton('Loop')
        self._btn_loop.setCheckable(True)
        self._btn_loop.toggled.connect(self.mpv_widget.set_loop)
        controls.addWidget(self._btn_loop)

        self._btn_auto = QtWidgets.QPushButton('AutoPlay')
        self._btn_auto.setCheckable(True)
        self._btn_auto.setChecked(True)
        self._btn_auto.toggled.connect(self.mpv_widget.set_auto_play)
        controls.addWidget(self._btn_auto)

        self._toggle_widgets.extend([btn_pause, btn_stop, btn_prev, btn_next, self._btn_loop, self._btn_auto])

        seek_container = QtWidgets.QWidget()
        seek_row = QtWidgets.QHBoxLayout(seek_container)
        seek_row.setContentsMargins(0, 0, 0, 0)
        left.addWidget(seek_container)
        self._toggle_widgets.append(seek_container)

        for sec in [-30, -10, -5]:
            btn = QtWidgets.QPushButton(f'{sec}s')
            btn.clicked.connect(lambda _, s=sec: self.mpv_widget.seek(s))
            seek_row.addWidget(btn)

        btn_fb = QtWidgets.QPushButton('|<')
        btn_fb.setToolTip('1 frame back')
        btn_fb.clicked.connect(self.mpv_widget.frame_back_step)
        seek_row.addWidget(btn_fb)

        btn_ff = QtWidgets.QPushButton('>|')
        btn_ff.setToolTip('1 frame forward')
        btn_ff.clicked.connect(self.mpv_widget.frame_step)
        seek_row.addWidget(btn_ff)

        for sec in [5, 10, 30]:
            btn = QtWidgets.QPushButton(f'+{sec}s')
            btn.clicked.connect(lambda _, s=sec: self.mpv_widget.seek(s))
            seek_row.addWidget(btn)

        seekbar_container = QtWidgets.QWidget()
        seek_bar_row = QtWidgets.QHBoxLayout(seekbar_container)
        seek_bar_row.setContentsMargins(0, 0, 0, 0)
        left.addWidget(seekbar_container)
        self._toggle_widgets.append(seekbar_container)

        self.time_label = QtWidgets.QLabel('00:00')
        seek_bar_row.addWidget(self.time_label)

        self.seek_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.seek_slider.setRange(0, 1000)
        self._seek_dragging = False
        self.seek_slider.sliderPressed.connect(lambda: setattr(self, '_seek_dragging', True))
        self.seek_slider.sliderReleased.connect(self._on_seek_released)
        seek_bar_row.addWidget(self.seek_slider, 1)

        self.duration_label = QtWidgets.QLabel('00:00')
        seek_bar_row.addWidget(self.duration_label)

        bottom_container = QtWidgets.QWidget()
        bottom_row = QtWidgets.QHBoxLayout(bottom_container)
        bottom_row.setContentsMargins(0, 0, 0, 0)
        left.addWidget(bottom_container)
        self._toggle_widgets.append(bottom_container)

        bottom_row.addWidget(QtWidgets.QLabel('Speed:'))
        speed_combo = QtWidgets.QComboBox()
        for spd in ['0.25', '0.5', '0.75', '1.0', '1.25', '1.5', '2.0', '3.0']:
            speed_combo.addItem(f'{spd}x', float(spd))
        speed_combo.setCurrentText('1.0x')
        speed_combo.currentIndexChanged.connect(
            lambda i: self.mpv_widget.set_speed(speed_combo.itemData(i))
        )
        bottom_row.addWidget(speed_combo)

        btn_fit = QtWidgets.QPushButton('Cover')
        btn_fit.setCheckable(True)
        btn_fit.setToolTip('Fit: black bars / Cover: fill & crop')
        btn_fit.toggled.connect(self.mpv_widget.set_fit_mode)
        bottom_row.addWidget(btn_fit)

        bottom_row.addStretch()

        btn_mute = QtWidgets.QPushButton('Mute')
        btn_mute.setCheckable(True)
        btn_mute.toggled.connect(self.mpv_widget.set_mute)
        bottom_row.addWidget(btn_mute)

        self._vol_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self._vol_slider.setRange(0, 100)
        self._vol_slider.setValue(100)
        self._vol_slider.setFixedWidth(120)
        self._vol_slider.valueChanged.connect(self.mpv_widget.set_volume)
        bottom_row.addWidget(self._vol_slider)

        self.status = QtWidgets.QLabel('Ready')
        left.addWidget(self.status)

        self._right_container = QtWidgets.QWidget()
        right = QtWidgets.QVBoxLayout(self._right_container)
        right.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._right_container)
        self._toggle_widgets.append(self._right_container)

        right.addWidget(QtWidgets.QLabel('Playlist'))

        self._playlist_widget = QtWidgets.QListWidget()
        self._playlist_widget.setFixedWidth(250)
        self._playlist_widget.itemDoubleClicked.connect(self._on_playlist_double_click)
        right.addWidget(self._playlist_widget, 1)

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._update_position)
        self._timer.start()

        self.mpv_widget.file_started.connect(self._on_file_started)
        self.mpv_widget.file_ended.connect(self._on_file_ended)

        self._controls_visible = True

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_F2:
            self._controls_visible = not self._controls_visible
            for w in self._toggle_widgets:
                w.setVisible(self._controls_visible)
            state = 'ON' if self._controls_visible else 'OFF'
            self.setWindowTitle(f'mpv Test - Controls {state} (F2=toggle)')
        else:
            super().keyPressEvent(event)

    def _format_time(self, seconds):
        if seconds is None:
            return '00:00'
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        return f'{h}:{m:02d}:{s:02d}' if h else f'{m:02d}:{s:02d}'

    def _update_position(self):
        pos = self.mpv_widget.time_pos
        dur = self.mpv_widget.duration
        self.time_label.setText(self._format_time(pos))
        self.duration_label.setText(self._format_time(dur))
        if not self._seek_dragging and pos is not None and dur:
            self.seek_slider.setValue(int(pos / dur * 1000))

    def _on_seek_released(self):
        self._seek_dragging = False
        dur = self.mpv_widget.duration
        if dur:
            target = self.seek_slider.value() / 1000.0 * dur
            self.mpv_widget.seek_absolute(target)

    def _refresh_playlist_widget(self):
        self._playlist_widget.clear()
        for path in self.mpv_widget._playlist:
            self._playlist_widget.addItem(os.path.basename(path))
        self._highlight_current()

    def _highlight_current(self):
        idx = self.mpv_widget._playlist_index
        self._playlist_widget.blockSignals(True)
        self._playlist_widget.setCurrentRow(idx)
        self._playlist_widget.blockSignals(False)

    def _on_playlist_double_click(self, item):
        row = self._playlist_widget.row(item)
        self.mpv_widget.play_index(row)

    def _open_file(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, 'Open Video', '',
            'Video Files (*.mp4 *.mkv *.webm *.avi *.mov *.wmv *.flv);;All Files (*)',
        )
        if not path:
            return
        video_exts = {'.mp4', '.mkv', '.webm', '.avi', '.mov', '.wmv', '.flv'}
        folder = os.path.dirname(path)
        siblings = sorted(
            os.path.join(folder, f) for f in os.listdir(folder)
            if os.path.splitext(f)[1].lower() in video_exts
        )
        idx = siblings.index(path) if path in siblings else 0
        self.mpv_widget.set_playlist(siblings, idx)
        self._refresh_playlist_widget()

    def _on_file_started(self, path):
        name = os.path.basename(path)
        pl = self.mpv_widget._playlist
        idx = self.mpv_widget._playlist_index
        self.status.setText(f'Playing: {name} ({idx + 1}/{len(pl)})')
        self._highlight_current()

    def _on_file_ended(self, path):
        name = os.path.basename(path) if path else '?'
        self.status.setText(f'Ended: {name}')


def main():
    app = QtWidgets.QApplication(sys.argv)
    win = TestWindow()
    win.show()

    if len(sys.argv) > 1:
        win.mpv_widget.load(sys.argv[1])
        win.status.setText(f'Playing: {sys.argv[1]}')

    sys.exit(app.exec())


if __name__ == '__main__':
    main()
