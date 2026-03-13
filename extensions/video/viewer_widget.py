from PySide6.QtCore import Qt, QTimer, QEvent, QPoint, QRectF, QPointF
from PySide6.QtGui import QCursor, QPalette, QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QSlider, QLabel, QAbstractButton,
)
from wafer.utils.formatting import dpix
from wafer.utils.logs import AppLogger
from wafer.core.actions.bridge import ActionKit, UI, Command
from wafer.app.viewer.viewer_settings import app_settings

DEFAULT_VOLUME = 50
_CONTROL_BAR_HEIGHT = 36
_HIDE_DELAY_MS = 3000
_POSITION_UPDATE_MS = 250
_VOLUME_POPUP_HIDE_MS = 400


def _format_time(seconds):
    if seconds is None or seconds < 0:
        return '00:00'
    total = int(seconds)
    m, s = divmod(total, 60)
    h, m = divmod(m, 60)
    return f'{h}:{m:02d}:{s:02d}' if h else f'{m:02d}:{s:02d}'


def _build_control_style():
    return f"""
    #seekSlider::groove:horizontal {{
        height: {dpix(4)}px;
        background: #555;
        border-radius: {dpix(2)}px;
    }}
    #seekSlider::handle:horizontal {{
        width: {dpix(12)}px;
        height: {dpix(12)}px;
        background: #fff;
        border-radius: {dpix(6)}px;
        margin: {-dpix(4)}px 0;
    }}
    #seekSlider::sub-page:horizontal {{
        background: #09f;
        border-radius: {dpix(2)}px;
    }}
    QLabel {{
        color: #bbb;
        font-size: {dpix(11)}px;
    }}
    """


def _build_volume_popup_style():
    return f"""
    #volumePopupSlider::groove:vertical {{
        width: {dpix(4)}px;
        background: #555;
        border-radius: {dpix(2)}px;
    }}
    #volumePopupSlider::handle:vertical {{
        width: {dpix(10)}px;
        height: {dpix(10)}px;
        background: #fff;
        border-radius: {dpix(5)}px;
        margin: 0 {-dpix(3)}px;
    }}
    #volumePopupSlider::sub-page:vertical {{
        background: #555;
        border-radius: {dpix(2)}px;
    }}
    #volumePopupSlider::add-page:vertical {{
        background: #09f;
        border-radius: {dpix(2)}px;
    }}
    """


class _MediaButton(QAbstractButton):

    def __init__(self, icon_key, size=28, padding=7, parent=None):
        super().__init__(parent)
        self._icon_key = icon_key
        self._padding = padding
        s = dpix(size)
        self.setFixedSize(s, s)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)

    def set_icon_key(self, key):
        self._icon_key = key
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.underMouse():
            p.setBrush(QColor(255, 255, 255, 30))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(self.rect(), dpix(3), dpix(3))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(220, 220, 220))
        r = QRectF(self.rect()).adjusted(dpix(self._padding), dpix(self._padding), -dpix(self._padding), -dpix(self._padding))
        getattr(self, f'_draw_{self._icon_key}', self._draw_play)(p, r)
        p.end()

    def _draw_play(self, p, r):
        ox = r.width() * 0.2
        path = QPainterPath()
        path.moveTo(QPointF(r.left() + ox, r.top()))
        path.lineTo(QPointF(r.right(), r.center().y()))
        path.lineTo(QPointF(r.left() + ox, r.bottom()))
        path.closeSubpath()
        p.drawPath(path)

    def _draw_pause(self, p, r):
        w = r.width() * 0.3
        p.drawRect(QRectF(r.left(), r.top(), w, r.height()))
        p.drawRect(QRectF(r.right() - w, r.top(), w, r.height()))

    def _draw_volume(self, p, r):
        sw = r.width() * 0.35
        sh = r.height() * 0.5
        sy = r.center().y() - sh / 2
        p.drawRect(QRectF(r.left(), sy, sw, sh))
        path = QPainterPath()
        path.moveTo(QPointF(r.left() + sw, sy))
        path.lineTo(QPointF(r.center().x() + sw * 0.3, r.top()))
        path.lineTo(QPointF(r.center().x() + sw * 0.3, r.bottom()))
        path.lineTo(QPointF(r.left() + sw, sy + sh))
        path.closeSubpath()
        p.drawPath(path)
        p.setBrush(Qt.BrushStyle.NoBrush)
        pen = QPen(QColor(220, 220, 220), dpix(1.5))
        p.setPen(pen)
        cx = r.center().x() + sw * 0.5
        for i, rad in enumerate([r.height() * 0.25, r.height() * 0.4]):
            arc_r = QRectF(cx - rad, r.center().y() - rad, rad * 2, rad * 2)
            p.drawArc(arc_r, -45 * 16, 90 * 16)

    def _draw_muted(self, p, r):
        sw = r.width() * 0.35
        sh = r.height() * 0.5
        sy = r.center().y() - sh / 2
        p.drawRect(QRectF(r.left(), sy, sw, sh))
        path = QPainterPath()
        path.moveTo(QPointF(r.left() + sw, sy))
        path.lineTo(QPointF(r.center().x() + sw * 0.3, r.top()))
        path.lineTo(QPointF(r.center().x() + sw * 0.3, r.bottom()))
        path.lineTo(QPointF(r.left() + sw, sy + sh))
        path.closeSubpath()
        p.drawPath(path)
        pen = QPen(QColor(220, 80, 80), dpix(2))
        p.setPen(pen)
        x1 = r.right() - r.width() * 0.25
        p.drawLine(QPointF(x1 - dpix(3), r.center().y() - dpix(3)),
                    QPointF(x1 + dpix(3), r.center().y() + dpix(3)))
        p.drawLine(QPointF(x1 + dpix(3), r.center().y() - dpix(3)),
                    QPointF(x1 - dpix(3), r.center().y() + dpix(3)))

    def enterEvent(self, event):
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.update()


class VolumePopup(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor(30, 30, 30, 230))
        self.setPalette(pal)
        self.setFixedSize(dpix(48), dpix(120))
        self.setMouseTracking(True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(dpix(6), dpix(8), dpix(6), dpix(8))
        self.slider = QSlider(Qt.Orientation.Vertical)
        self.slider.setObjectName('volumePopupSlider')
        self.slider.setRange(0, 100)
        self.slider.setValue(DEFAULT_VOLUME)
        layout.addWidget(self.slider)
        self.setStyleSheet(_build_volume_popup_style())

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(_VOLUME_POPUP_HIDE_MS)
        self._hide_timer.timeout.connect(self.hide)

    def show_at(self, global_pos):
        self.move(global_pos.x() - self.width() // 2, global_pos.y() - self.height())
        self.show()
        self._hide_timer.stop()

    def enterEvent(self, event):
        super().enterEvent(event)
        self._hide_timer.stop()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self._hide_timer.start()


class VideoControlBar(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self.setAutoFillBackground(True)
        p = self.palette()
        p.setColor(QPalette.ColorRole.Window, QColor(20, 20, 20, 200))
        self.setPalette(p)
        self.setMouseTracking(True)
        self._setup_ui()
        self.setStyleSheet(_build_control_style())

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(dpix(10), dpix(1), dpix(10), dpix(1))

        self.btn_play = _MediaButton('play', padding=dpix(8))
        layout.addWidget(self.btn_play)

        layout.addSpacing(dpix(3))

        self.seek_slider = QSlider(Qt.Orientation.Horizontal)
        self.seek_slider.setObjectName('seekSlider')
        self.seek_slider.setRange(0, 1000)
        layout.addWidget(self.seek_slider, 1)

        layout.addSpacing(dpix(5))

        self.time_label = QLabel('00:00 / 00:00')
        layout.addWidget(self.time_label)

        layout.addSpacing(dpix(3))

        self.btn_volume = _MediaButton('volume', padding=dpix(6))
        layout.addWidget(self.btn_volume)

        self.volume_popup = VolumePopup()
        self.volume_popup.hide()
        self.volume_slider = self.volume_popup.slider

    def show_volume_popup(self):
        pos = self.btn_volume.mapToGlobal(QPoint(
            self.btn_volume.width() // 2, 0))
        self.volume_popup.show_at(pos)

    def hide_volume_popup(self):
        self.volume_popup._hide_timer.start()

    def enterEvent(self, event):
        super().enterEvent(event)
        p = self.parent()
        if isinstance(p, VideoViewerWidget):
            p._on_control_enter()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        p = self.parent()
        if isinstance(p, VideoViewerWidget):
            p._on_control_leave()


class VideoViewerWidget(QWidget, ActionKit.UIMixin):

    _mpv_mod = None
    _mpv_checked = False

    @classmethod
    def _ensure_mpv_mod(cls):
        if cls._mpv_checked:
            return cls._mpv_mod is not None
        cls._mpv_checked = True
        try:
            import mpv
            cls._mpv_mod = mpv
            return True
        except (OSError, ImportError):
            return False

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self._path = None
        self._player = None
        self._volume = app_settings.get("video/volume", DEFAULT_VOLUME, int)
        self._muted = app_settings.get("video/muted", False, bool)
        self._speed = 1.0
        self._cover_mode = False
        self._looping = False
        self._seek_dragging = False
        self._controls_visible = False

        self._player_area = QWidget(self)
        self._player_area.setAttribute(Qt.WidgetAttribute.WA_NativeWindow, True)
        self._player_area.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self._player_area.setMouseTracking(True)
        pa_palette = self._player_area.palette()
        pa_palette.setColor(QPalette.ColorRole.Window, QColor(0, 0, 0))
        self._player_area.setAutoFillBackground(True)
        self._player_area.setPalette(pa_palette)
        self._player_area.installEventFilter(self)

        self._control_bar = VideoControlBar(self)
        self._control_bar.hide()

        self._control_bar.btn_play.clicked.connect(self.toggle_pause)
        self._control_bar.btn_volume.clicked.connect(self.toggle_mute)
        self._control_bar.volume_slider.valueChanged.connect(self._on_volume_changed)
        self._control_bar.seek_slider.sliderPressed.connect(self._on_seek_pressed)
        self._control_bar.seek_slider.sliderReleased.connect(self._on_seek_released)

        self._control_bar.volume_slider.blockSignals(True)
        self._control_bar.volume_slider.setValue(self._volume)
        self._control_bar.volume_slider.blockSignals(False)
        self._update_volume_icon()

        self._volume_hover_timer = QTimer(self)
        self._volume_hover_timer.setSingleShot(True)
        self._volume_hover_timer.setInterval(150)
        self._volume_hover_timer.timeout.connect(self._control_bar.show_volume_popup)
        self._control_bar.btn_volume.installEventFilter(self)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(_HIDE_DELAY_MS)
        self._hide_timer.timeout.connect(self._hide_controls)

        self._pos_timer = QTimer(self)
        self._pos_timer.setInterval(_POSITION_UPDATE_MS)
        self._pos_timer.timeout.connect(self._update_position)

        self.init_command_binding("VideoView")
        UI.register_instance("VideoViewerWidget", self)

    def extend_context(self, ctx, cmd, event=None, key=None, source=None):
        return {"path": self._path, "paths": [self._path] if self._path else []}

    def _ensure_player(self):
        if self._player is not None:
            return
        if not self._ensure_mpv_mod():
            return
        try:
            self._player = self._mpv_mod.MPV(
                wid=str(int(self._player_area.winId())),
                vo='gpu',
                hwdec='auto',
                keep_open='yes',
                idle='yes',
                osd_level=0,
                input_default_bindings='no',
                input_vo_keyboard='no',
            )
            self._player.volume = self._volume
            self._player.mute = self._muted
            self._player.speed = self._speed
            self._player['panscan'] = 1.0 if self._cover_mode else 0.0
            self._player['loop-file'] = 'inf' if self._looping else 'no'
        except Exception as e:
            AppLogger.error(f'Failed to create mpv player: {e}', exc=e)
            self._player = None

    def load(self, path):
        self._path = path
        self._ensure_player()
        if self._player:
            self._player.play(path)
            self._player.pause = False
        self._pos_timer.start()
        self._update_play_button()

    def clear(self):
        self._path = None
        self._stop_playback()
        self._pos_timer.stop()
        self._hide_controls()

    def _stop_playback(self):
        if self._player:
            try:
                self._player.command('stop')
            except Exception:
                pass

    def toggle_pause(self):
        if not self._player:
            return
        self._player.pause = not self._player.pause
        self._update_play_button()

    def seek(self, seconds):
        if self._player:
            self._player.seek(seconds)

    def seek_absolute(self, seconds):
        if self._player:
            self._player.seek(seconds, reference='absolute')

    def frame_step(self):
        if self._player:
            self._player.frame_step()

    def frame_back_step(self):
        if self._player:
            self._player.frame_back_step()

    def set_volume(self, volume):
        self._volume = max(0, min(100, int(volume)))
        if self._player:
            self._player.volume = self._volume
        self._control_bar.volume_slider.blockSignals(True)
        self._control_bar.volume_slider.setValue(self._volume)
        self._control_bar.volume_slider.blockSignals(False)
        self._update_volume_icon()
        app_settings.set("video/volume", self._volume)

    def toggle_mute(self):
        self._muted = not self._muted
        if self._player:
            self._player.mute = self._muted
        self._update_volume_icon()
        Command.set_checked("vview.toggle_mute", self._muted)
        app_settings.set("video/muted", self._muted)

    def set_speed(self, speed):
        self._speed = max(0.25, min(3.0, float(speed)))
        if self._player:
            self._player.speed = self._speed

    def toggle_fit_mode(self):
        self._cover_mode = not self._cover_mode
        if self._player:
            self._player['panscan'] = 1.0 if self._cover_mode else 0.0
        Command.set_checked("vview.toggle_fit_mode", self._cover_mode)

    def toggle_loop(self):
        self._looping = not self._looping
        if self._player:
            self._player['loop-file'] = 'inf' if self._looping else 'no'
        Command.set_checked("vview.toggle_loop", self._looping)

    def _on_volume_changed(self, value):
        self._volume = value
        if self._muted and value > 0:
            self._muted = False
            if self._player:
                self._player.mute = False
            Command.set_checked("vview.toggle_mute", False)
            app_settings.set("video/muted", False)
        if self._player:
            self._player.volume = value
        self._update_volume_icon()
        app_settings.set("video/volume", self._volume)

    def _on_seek_pressed(self):
        self._seek_dragging = True

    def _on_seek_released(self):
        self._seek_dragging = False
        if not self._player:
            return
        try:
            dur = self._player.duration
        except Exception:
            return
        if dur:
            target = self._control_bar.seek_slider.value() / 1000.0 * dur
            self.seek_absolute(target)

    def _update_play_button(self):
        paused = self._player.pause if self._player else True
        self._control_bar.btn_play.set_icon_key('play' if paused else 'pause')

    def _update_volume_icon(self):
        self._control_bar.btn_volume.set_icon_key('muted' if self._muted else 'volume')

    def _update_position(self):
        if not self._player:
            return
        try:
            pos = self._player.time_pos
            dur = self._player.duration
        except Exception:
            return
        self._control_bar.time_label.setText(
            f'{_format_time(pos)} / {_format_time(dur)}')
        if not self._seek_dragging and pos is not None and dur:
            self._control_bar.seek_slider.blockSignals(True)
            self._control_bar.seek_slider.setValue(int(pos / dur * 1000))
            self._control_bar.seek_slider.blockSignals(False)
        self._update_play_button()

    def _show_controls(self):
        if not self._controls_visible:
            self._controls_visible = True
            self._control_bar.show()
            self._control_bar.raise_()
        self._hide_timer.start()

    def _hide_controls(self):
        self._controls_visible = False
        self._control_bar.hide()
        self._control_bar.volume_popup.hide()
        self._hide_timer.stop()

    def _on_control_enter(self):
        self._hide_timer.stop()

    def _on_control_leave(self):
        pos = QCursor.pos()
        local = self.mapFromGlobal(pos)
        if self.rect().contains(local):
            self._hide_timer.start()
        else:
            self._hide_controls()

    def eventFilter(self, obj, event):
        if obj is self._control_bar.btn_volume:
            if event.type() == QEvent.Type.Enter:
                self._volume_hover_timer.start()
            elif event.type() == QEvent.Type.Leave:
                self._volume_hover_timer.stop()
                self._control_bar.hide_volume_popup()
        if obj is self._player_area:
            t = event.type()
            if t == QEvent.Type.MouseMove or t == QEvent.Type.Enter:
                self._show_controls()
            elif t == QEvent.Type.Leave:
                if not self._control_bar.underMouse():
                    self._hide_timer.start()
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        w, h = self.width(), self.height()
        self._player_area.setGeometry(0, 0, w, h)
        bar_h = dpix(_CONTROL_BAR_HEIGHT)
        self._control_bar.setGeometry(0, h - bar_h, w, bar_h)
        if self._controls_visible:
            self._control_bar.raise_()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._stop_playback()
        self._pos_timer.stop()
        self._hide_controls()

    def cleanup(self):
        self._pos_timer.stop()
        self._hide_timer.stop()
        self._control_bar.volume_popup.hide()
        if self._player:
            self._player.terminate()
            self._player = None
