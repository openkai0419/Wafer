import os
import sys
from functools import partial

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
os.environ['PATH'] = SCRIPT_DIR + os.pathsep + os.environ.get('PATH', '')
if hasattr(os, 'add_dll_directory'):
    os.add_dll_directory(SCRIPT_DIR)

import mpv

from PySide6 import QtCore, QtWidgets, QtGui
from PySide6.QtCore import Qt, QRect, QRectF, QPointF, Signal, Slot
from PySide6.QtOpenGLWidgets import QOpenGLWidget


def _get_proc_address(_, name):
    from PySide6.QtGui import QOpenGLContext
    ctx = QOpenGLContext.currentContext()
    if ctx is None:
        return 0
    addr = ctx.getProcAddress(name)
    return int(addr) if addr else 0


_get_proc_address_c = mpv.MpvGlGetProcAddressFn(_get_proc_address)


class MpvGLWidget(QOpenGLWidget):

    file_started = Signal(str)
    file_ended = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 240)

        self._playlist: list[str] = []
        self._playlist_index = -1
        self._loop = False
        self._auto_play = True
        self._transitioning = False
        self._volume = 100
        self._mute = False
        self._speed = 1.0

        self.player: mpv.MPV | None = None
        self._ctx: mpv.MpvRenderContext | None = None
        self._frame_ready = False

    def initializeGL(self):
        self.player = mpv.MPV(
            vo='libmpv',
            hwdec='auto',
            keep_open='yes',
            idle='yes',
            log_handler=self._log_handler,
        )
        self.player.volume = self._volume
        self.player.mute = self._mute
        self.player.speed = self._speed
        self.player.observe_property('eof-reached', self._on_eof_reached)

        @self.player.event_callback('end-file')
        def _on_end(event):
            QtCore.QMetaObject.invokeMethod(
                self, '_handle_end_file', Qt.ConnectionType.QueuedConnection,
            )

        self._ctx = mpv.MpvRenderContext(
            self.player, 'opengl',
            opengl_init_params={'get_proc_address': _get_proc_address_c},
        )
        self._ctx.update_cb = self._on_mpv_frame

    def _on_mpv_frame(self):
        self._frame_ready = True
        QtCore.QMetaObject.invokeMethod(
            self, '_request_update', Qt.ConnectionType.QueuedConnection,
        )

    @Slot()
    def _request_update(self):
        if self._frame_ready and self.isVisible():
            self.update()

    def paintGL(self):
        if self._ctx is None:
            return
        self._frame_ready = False
        ratio = self.devicePixelRatioF()
        w = int(self.width() * ratio)
        h = int(self.height() * ratio)
        fbo = self.defaultFramebufferObject()
        self._ctx.render(
            opengl_fbo={'w': w, 'h': h, 'fbo': fbo},
            flip_y=True,
        )

    def resizeGL(self, w, h):
        pass

    def _log_handler(self, loglevel, component, message):
        if loglevel in ('error', 'fatal'):
            print(f'[mpv/{loglevel}] {component}: {message}')

    def _on_eof_reached(self, _name, value):
        if value:
            QtCore.QMetaObject.invokeMethod(
                self, '_handle_eof', Qt.ConnectionType.QueuedConnection,
            )

    @property
    def _current_path(self):
        if self._playlist and 0 <= self._playlist_index < len(self._playlist):
            return self._playlist[self._playlist_index]
        return ''

    @Slot()
    def _handle_eof(self):
        if self._transitioning:
            return
        self.file_ended.emit(self._current_path)
        if self._loop:
            self._replay_current()
        elif self._auto_play and len(self._playlist) > 1:
            self._advance_playlist()

    @Slot()
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

    @property
    def paused(self):
        return self.player.pause if self.player else True

    def stop(self):
        if self.player is not None:
            self._transitioning = True
            self.player.terminate()
            self.player = None

    def set_volume(self, vol):
        self._volume = max(0, min(100, vol))
        if self.player is not None:
            self.player.volume = self._volume

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

    def set_speed(self, speed):
        self._speed = speed
        if self.player is not None:
            self.player.speed = speed

    @property
    def duration(self):
        return self.player.duration if self.player else None

    @property
    def time_pos(self):
        return self.player.time_pos if self.player else None

    def cleanup(self):
        if self._ctx is not None:
            self._ctx.free()
            self._ctx = None
        if self.player is not None:
            self._transitioning = True
            self.player.terminate()
            self.player = None


_COL_ACCENT = QtGui.QColor(224, 64, 80)
_COL_W = QtGui.QColor(255, 255, 255)
_COL_W85 = QtGui.QColor(255, 255, 255, 216)
_COL_DIM = QtGui.QColor(255, 255, 255, 50)
_COL_HOVER = QtGui.QColor(255, 255, 255, 30)
_COL_BG_POPUP = QtGui.QColor(24, 24, 24, 235)
_FONT_TIME = QtGui.QFont('Consolas', 9)
_FONT_VOL = QtGui.QFont('Consolas', 8, QtGui.QFont.Weight.Bold)


def _draw_play(p: QtGui.QPainter, c: QPointF, s: float):
    hs = s / 2
    path = QtGui.QPainterPath()
    path.moveTo(c.x() - hs * 0.4, c.y() - hs)
    path.lineTo(c.x() + hs * 0.7, c.y())
    path.lineTo(c.x() - hs * 0.4, c.y() + hs)
    path.closeSubpath()
    p.fillPath(path, _COL_W)


def _draw_pause(p: QtGui.QPainter, c: QPointF, s: float):
    bw, bh, gap = s * 0.18, s * 0.65, s * 0.14
    p.fillRect(QRectF(c.x() - gap - bw, c.y() - bh / 2, bw, bh), _COL_W)
    p.fillRect(QRectF(c.x() + gap, c.y() - bh / 2, bw, bh), _COL_W)


def _draw_vol(p: QtGui.QPainter, c: QPointF, s: float, muted: bool):
    hs = s / 2
    x0, cy = c.x() - hs, c.y()
    speaker = QtGui.QPainterPath()
    speaker.moveTo(x0, cy - hs * 0.25)
    speaker.lineTo(x0 + hs * 0.35, cy - hs * 0.25)
    speaker.lineTo(x0 + hs * 0.75, cy - hs * 0.6)
    speaker.lineTo(x0 + hs * 0.75, cy + hs * 0.6)
    speaker.lineTo(x0 + hs * 0.35, cy + hs * 0.25)
    speaker.lineTo(x0, cy + hs * 0.25)
    speaker.closeSubpath()
    p.fillPath(speaker, _COL_W)
    pen = QtGui.QPen(_COL_W, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    if muted:
        x1 = x0 + hs * 1.0
        p.drawLine(QPointF(x1, cy - hs * 0.35), QPointF(x1 + hs * 0.6, cy + hs * 0.35))
        p.drawLine(QPointF(x1 + hs * 0.6, cy - hs * 0.35), QPointF(x1, cy + hs * 0.35))
    else:
        r1 = hs * 0.45
        p.drawArc(QRectF(x0 + hs * 0.85 - r1, cy - r1, r1 * 2, r1 * 2), -40 * 16, 80 * 16)
        r2 = hs * 0.75
        p.drawArc(QRectF(x0 + hs * 0.85 - r2, cy - r2, r2 * 2, r2 * 2), -35 * 16, 70 * 16)
    p.setPen(Qt.PenStyle.NoPen)


class ControlOverlay(QtWidgets.QWidget):

    BAR_H = 44
    ICON = 28
    GAP = 10
    PAD = 14
    GROOVE_H = 4
    HANDLE_R = 7
    VOL_POP_W = 36
    VOL_POP_H = 120
    VOL_PAD_TOP = 22
    VOL_PAD_BOT = 10
    VOL_GROOVE_W = 4
    VOL_HANDLE_R = 6
    FADE_MS = 250
    HIDE_MS = 2500

    play_toggled = Signal()
    seek_changed = Signal(float)
    mute_toggled = Signal()
    volume_changed = Signal(int)
    fullscreen_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.is_playing = False
        self.seek_ratio = 0.0
        self.time_text = '0:00 / 0:00'
        self.is_muted = False
        self.volume = 100

        self._opacity = 0.0
        self._seek_drag = False
        self._vol_drag = False
        self._hover = ''
        self._vol_shown = False

        self._rects: dict[str, QRect] = {}

        self._fade_anim = QtCore.QVariantAnimation(self)
        self._fade_anim.setDuration(self.FADE_MS)
        self._fade_anim.setEasingCurve(QtCore.QEasingCurve.Type.OutCubic)
        self._fade_anim.valueChanged.connect(self._on_opacity_tick)

        self._hide_timer = QtCore.QTimer(self, singleShot=True)
        self._hide_timer.timeout.connect(self.fade_out)

        self._click_timer = QtCore.QTimer(self, singleShot=True)
        self._click_timer.setInterval(300)
        self._click_timer.timeout.connect(self._on_single_click)

        self._shown_state = False

    def _on_opacity_tick(self, val):
        self._opacity = val
        self.update()

    def _layout(self):
        w, h = self.width(), self.height()
        bar_top = h - self.BAR_H
        cy = bar_top + self.BAR_H // 2
        x = self.PAD
        s = self.ICON

        self._rects['bar'] = QRect(0, bar_top, w, self.BAR_H)
        self._rects['play'] = QRect(x, cy - s // 2, s, s)
        x += s + self.GAP

        rx = w - self.PAD
        self._rects['vol_btn'] = QRect(rx - s, cy - s // 2, s, s)
        rx -= s + self.GAP

        fm = QtGui.QFontMetrics(_FONT_TIME)
        tw = fm.horizontalAdvance('00:00:00 / 00:00:00') + 4
        self._rects['time'] = QRect(rx - tw, bar_top, tw, self.BAR_H)
        rx -= tw + self.GAP

        seek_w = max(rx - x, 1)
        self._rects['seek'] = QRect(x, cy - 10, seek_w, 20)
        self._rects['groove'] = QRect(x, cy - self.GROOVE_H // 2, seek_w, self.GROOVE_H)

        vol_btn = self._rects['vol_btn']
        vx = vol_btn.center().x() - self.VOL_POP_W // 2
        vy = bar_top - self.VOL_POP_H - 4
        self._rects['vol_pop'] = QRect(vx, vy, self.VOL_POP_W, self.VOL_POP_H)

        vt = vy + self.VOL_PAD_TOP
        vb = vy + self.VOL_POP_H - self.VOL_PAD_BOT
        vcx = vx + self.VOL_POP_W // 2
        self._rects['vol_track'] = QRect(
            vcx - self.VOL_GROOVE_W // 2, vt, self.VOL_GROOVE_W, vb - vt
        )
        self._rects['vol_area'] = QRect(vx, vt - 4, self.VOL_POP_W, vb - vt + 8)
        self._rects['video'] = QRect(0, 0, w, bar_top)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout()

    def paintEvent(self, event):
        if not self._rects or self._opacity < 0.01:
            return
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        p.setOpacity(self._opacity)
        self._paint_bar(p)
        if self._vol_shown:
            self._paint_vol_popup(p)
        p.end()

    def _paint_bar(self, p):
        bar = self._rects['bar']
        grad = QtGui.QLinearGradient(bar.x(), bar.y(), bar.x(), bar.bottom())
        grad.setColorAt(0.0, QtGui.QColor(0, 0, 0, 0))
        grad.setColorAt(0.3, QtGui.QColor(0, 0, 0, 160))
        grad.setColorAt(1.0, QtGui.QColor(0, 0, 0, 220))
        p.fillRect(QRectF(bar), grad)

        r = self._rects['play']
        if self._hover == 'play':
            p.setBrush(_COL_HOVER)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(r)
        c = QPointF(r.center())
        if self.is_playing:
            _draw_pause(p, c, self.ICON)
        else:
            _draw_play(p, c, self.ICON)

        gr = self._rects['groove']
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_COL_DIM)
        p.drawRoundedRect(QRectF(gr), 2, 2)
        fw = gr.width() * self.seek_ratio
        if fw > 0:
            p.setBrush(_COL_ACCENT)
            p.drawRoundedRect(QRectF(gr.x(), gr.y(), fw, gr.height()), 2, 2)
        hx = gr.x() + fw
        hy = gr.y() + gr.height() / 2.0
        hr = self.HANDLE_R + 1 if self._hover == 'seek' or self._seek_drag else self.HANDLE_R
        p.setBrush(_COL_W)
        p.drawEllipse(QPointF(hx, hy), hr, hr)

        tr = self._rects['time']
        p.setPen(_COL_W85)
        p.setFont(_FONT_TIME)
        p.drawText(QRectF(tr), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   self.time_text)

        vr = self._rects['vol_btn']
        if self._hover == 'vol_btn':
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_COL_HOVER)
            p.drawEllipse(vr)
        _draw_vol(p, QPointF(vr.center()), self.ICON, self.is_muted)

    def _paint_vol_popup(self, p):
        pop = self._rects['vol_pop']
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_COL_BG_POPUP)
        p.drawRoundedRect(QRectF(pop), 8, 8)

        p.setPen(_COL_W85)
        p.setFont(_FONT_VOL)
        label_r = QRectF(pop.x(), pop.y() + 4, pop.width(), self.VOL_PAD_TOP - 4)
        p.drawText(label_r, Qt.AlignmentFlag.AlignCenter, str(self.volume))

        vt = self._rects['vol_track']
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_COL_DIM)
        p.drawRoundedRect(QRectF(vt), 2, 2)

        ratio = self.volume / 100.0
        fill_h = vt.height() * ratio
        fy = vt.y() + vt.height() - fill_h
        p.setBrush(_COL_W)
        p.drawRoundedRect(QRectF(vt.x(), fy, vt.width(), fill_h), 2, 2)

        cx = vt.x() + vt.width() / 2.0
        p.drawEllipse(QPointF(cx, fy), self.VOL_HANDLE_R, self.VOL_HANDLE_R)

    def _hit(self, pos):
        if self._vol_shown:
            va = self._rects.get('vol_area')
            if va and va.contains(pos):
                return 'vol_slider'
            vp = self._rects.get('vol_pop')
            if vp and vp.contains(pos):
                return 'vol_pop'
        for name in ('play', 'vol_btn', 'seek'):
            r = self._rects.get(name)
            if r and r.contains(pos):
                return name
        bar = self._rects.get('bar')
        if bar and bar.contains(pos):
            return 'bar'
        return 'video'

    def show_controls(self):
        self._hide_timer.start(self.HIDE_MS)
        if self._shown_state:
            return
        self._shown_state = True
        self._fade_anim.stop()
        self._fade_anim.setStartValue(self._opacity)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.start()

    def fade_out(self):
        if self._seek_drag or self._vol_drag or self._vol_shown:
            self._hide_timer.start(self.HIDE_MS)
            return
        self._shown_state = False
        self._fade_anim.stop()
        self._fade_anim.setStartValue(self._opacity)
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.start()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position().toPoint()
        zone = self._hit(pos)
        if zone == 'play':
            self.play_toggled.emit()
        elif zone == 'vol_btn':
            self.mute_toggled.emit()
        elif zone == 'seek':
            self._seek_drag = True
            self._hide_timer.stop()
            self._update_seek(event.position().x())
        elif zone == 'vol_slider':
            self._vol_drag = True
            self._hide_timer.stop()
            self._update_vol(event.position().y())
        elif zone == 'video':
            self._click_timer.start()

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        if self._seek_drag:
            self._update_seek(event.position().x())
            return
        if self._vol_drag:
            self._update_vol(event.position().y())
            return

        new_hover = self._hit(pos)
        if new_hover != self._hover:
            self._hover = new_hover
            cursor = Qt.CursorShape.PointingHandCursor if new_hover in (
                'play', 'vol_btn', 'seek', 'vol_slider'
            ) else Qt.CursorShape.ArrowCursor
            self.setCursor(cursor)
            self.update()

        vol_btn = self._rects.get('vol_btn')
        vol_pop = self._rects.get('vol_pop')
        in_vol_zone = (
            (vol_btn and vol_btn.adjusted(-6, -6, 6, 6).contains(pos))
            or (vol_pop and vol_pop.adjusted(-6, -6, 6, 6).contains(pos))
        )
        if in_vol_zone and not self._vol_shown:
            self._vol_shown = True
            self.update()
        elif not in_vol_zone and self._vol_shown and not self._vol_drag:
            self._vol_shown = False
            self.update()

        self.show_controls()

    def mouseReleaseEvent(self, event):
        if self._seek_drag:
            self._seek_drag = False
            self.seek_changed.emit(self.seek_ratio)
            self._hide_timer.start(self.HIDE_MS)
        if self._vol_drag:
            self._vol_drag = False
            self._hide_timer.start(self.HIDE_MS)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint()
            zone = self._hit(pos)
            if zone == 'video':
                self._click_timer.stop()
                self.fullscreen_requested.emit()

    def _on_single_click(self):
        self.play_toggled.emit()

    def _update_seek(self, x):
        gr = self._rects.get('groove')
        if not gr or gr.width() == 0:
            return
        ratio = max(0.0, min(1.0, (x - gr.x()) / gr.width()))
        if ratio != self.seek_ratio:
            self.seek_ratio = ratio
            self.update()

    def _update_vol(self, y):
        vt = self._rects.get('vol_track')
        if not vt or vt.height() == 0:
            return
        ratio = 1.0 - max(0.0, min(1.0, (y - vt.y()) / vt.height()))
        new_vol = max(0, min(100, int(ratio * 100 + 0.5)))
        if new_vol != self.volume:
            self.volume = new_vol
            self.volume_changed.emit(new_vol)
            self.update()

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        v = max(0, min(100, self.volume + (5 if delta > 0 else -5)))
        if v != self.volume:
            self.volume = v
            self.volume_changed.emit(v)
            self.show_controls()
            self.update()

    def leaveEvent(self, event):
        self._hover = ''
        if self._vol_shown and not self._vol_drag:
            self._vol_shown = False
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key.Key_Space:
            self.play_toggled.emit()
        elif key == Qt.Key.Key_Left:
            self.seek_changed.emit(max(0.0, self.seek_ratio - 0.02))
        elif key == Qt.Key.Key_Right:
            self.seek_changed.emit(min(1.0, self.seek_ratio + 0.02))
        elif key == Qt.Key.Key_Up:
            v = min(100, self.volume + 5)
            self.volume = v
            self.volume_changed.emit(v)
            self.show_controls()
            self.update()
        elif key == Qt.Key.Key_Down:
            v = max(0, self.volume - 5)
            self.volume = v
            self.volume_changed.emit(v)
            self.show_controls()
            self.update()
        elif key == Qt.Key.Key_M:
            self.mute_toggled.emit()
        elif key in (Qt.Key.Key_F, Qt.Key.Key_F11):
            self.fullscreen_requested.emit()
        elif key == Qt.Key.Key_Escape:
            if self.window().isFullScreen():
                self.fullscreen_requested.emit()
        else:
            super().keyPressEvent(event)


class VideoPlayer(QtWidgets.QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet('background: black;')
        self.mpv = MpvGLWidget(self)
        self.overlay = ControlOverlay(self)
        self.overlay.play_toggled.connect(self._toggle_pause)
        self.overlay.seek_changed.connect(self._on_seek)
        self.overlay.mute_toggled.connect(self._toggle_mute)
        self.overlay.volume_changed.connect(self._on_vol)
        self.overlay.fullscreen_requested.connect(self._toggle_fullscreen)

        self._poll_timer = QtCore.QTimer(self, interval=200)
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.mpv.setGeometry(self.rect())
        self.overlay.setGeometry(self.rect())
        self.overlay.raise_()

    def showEvent(self, event):
        super().showEvent(event)
        self.overlay.raise_()
        self.overlay.setFocus()

    def _toggle_pause(self):
        self.mpv.toggle_pause()
        self.overlay.is_playing = not self.mpv.paused
        self.overlay.update()

    def _on_seek(self, ratio):
        dur = self.mpv.duration
        if dur:
            self.mpv.seek_absolute(ratio * dur)
        self.overlay.show_controls()

    def _toggle_mute(self):
        new = not self.mpv._mute
        self.mpv.set_mute(new)
        self.overlay.is_muted = new
        self.overlay.update()

    def _on_vol(self, val):
        self.mpv.set_volume(val)
        if val == 0:
            self.overlay.is_muted = True
        elif self.mpv._mute:
            self.mpv.set_mute(False)
            self.overlay.is_muted = False
        self.overlay.update()

    def _toggle_fullscreen(self):
        w = self.window()
        if w.isFullScreen():
            w.showNormal()
        else:
            w.showFullScreen()

    @staticmethod
    def _fmt(sec):
        if sec is None:
            return '0:00'
        s = max(0, int(sec))
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        return f'{h}:{m:02d}:{s:02d}' if h else f'{m}:{s:02d}'

    def _poll(self):
        pos = self.mpv.time_pos
        dur = self.mpv.duration
        self.overlay.time_text = f'{self._fmt(pos)} / {self._fmt(dur)}'
        self.overlay.is_playing = not self.mpv.paused
        if not self.overlay._seek_drag and pos is not None and dur:
            self.overlay.seek_ratio = pos / dur
        if self.overlay.isVisible():
            self.overlay.update()

    def closeEvent(self, event):
        self._poll_timer.stop()
        self.mpv.cleanup()
        super().closeEvent(event)


class TestWindow(QtWidgets.QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle('mpv OpenGL Player')
        self.resize(960, 600)
        self._player = VideoPlayer()
        self.setCentralWidget(self._player)
        menu = self.menuBar().addMenu('File')
        act = QtGui.QAction('Open...', self)
        act.setShortcut('Ctrl+O')
        act.triggered.connect(self._open)
        menu.addAction(act)

    def _open(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, 'Open Video', '',
            'Video (*.mp4 *.mkv *.webm *.avi *.mov *.wmv *.flv);;All (*)',
        )
        if not path:
            return
        exts = {'.mp4', '.mkv', '.webm', '.avi', '.mov', '.wmv', '.flv'}
        folder = os.path.dirname(path)
        siblings = sorted(
            os.path.join(folder, f) for f in os.listdir(folder)
            if os.path.splitext(f)[1].lower() in exts
        )
        idx = siblings.index(path) if path in siblings else 0
        self._player.mpv.set_playlist(siblings, idx)

    def closeEvent(self, event):
        self._player.close()
        super().closeEvent(event)


def main():
    QtWidgets.QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QtWidgets.QApplication(sys.argv)
    win = TestWindow()
    win.show()
    if len(sys.argv) > 1:
        win._player.mpv.load(sys.argv[1])
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
