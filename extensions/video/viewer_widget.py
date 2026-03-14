from PySide6.QtCore import Qt, QTimer, QEvent, QPoint, QRectF
from PySide6.QtGui import QCursor, QPalette, QColor, QPainter
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QSlider, QLabel, QAbstractButton, QApplication,
)
from wafer.utils.formatting import dpix
from wafer.utils.logs import AppLogger
from wafer.core.actions.bridge import ActionKit, UI, Command
from wafer.core.color.theme import ThemeManager
from wafer.core.qt.icon_engine import icon_draw

DEFAULT_VOLUME = 50
_CONTROL_BAR_HEIGHT = 32
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


def _build_control_style(palette):
    return f"""
    #seekSlider::groove:horizontal {{
        height: {dpix(4)}px;
        background: {palette.border_default};
        border-radius: {dpix(2)}px;
    }}
    #seekSlider::handle:horizontal {{
        width: {dpix(12)}px;
        height: {dpix(12)}px;
        background: {palette.text_primary};
        border-radius: {dpix(6)}px;
        margin: {-dpix(4)}px 0;
    }}
    #seekSlider::sub-page:horizontal {{
        background: {palette.accent};
        border-radius: {dpix(2)}px;
    }}
    QLabel {{
        color: {palette.text_primary};
        font-size: {dpix(11)}px;
    }}
    """


def _build_volume_popup_style(palette):
    return f"""
    #volumePopupSlider::groove:vertical {{
        width: {dpix(4)}px;
        background: {palette.border_default};
        border-radius: {dpix(2)}px;
    }}
    #volumePopupSlider::handle:vertical {{
        width: {dpix(10)}px;
        height: {dpix(10)}px;
        background: {palette.text_primary};
        border-radius: {dpix(5)}px;
        margin: 0 {-dpix(3)}px;
    }}
    #volumePopupSlider::sub-page:vertical {{
        background: {palette.border_default};
        border-radius: {dpix(2)}px;
    }}
    #volumePopupSlider::add-page:vertical {{
        background: {palette.accent};
        border-radius: {dpix(2)}px;
    }}
    """


class _MediaButton(QAbstractButton):

    def __init__(self, icon_key, size=28, padding=0.25, parent=None):
        super().__init__(parent)
        self._icon_key = icon_key
        self._padding = max(0.0, min(0.5, padding))
        s = dpix(size)
        self.setFixedSize(s, s)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)

    def set_icon_key(self, key):
        self._icon_key = key
        self.update()

    def paintEvent(self, event):
        palette = ThemeManager.instance().palette
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.underMouse():
            hover = QColor(palette.text_primary)
            hover.setAlpha(30)
            p.setBrush(hover)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(self.rect(), dpix(3), dpix(3))
        rect = QRectF(self.rect())
        dx = rect.width() * self._padding
        dy = rect.height() * self._padding
        r = rect.adjusted(dx, dy, -dx, -dy)
        icon_draw(self._icon_key, p, r, QColor(palette.text_primary))
        p.end()

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
        self.setFixedSize(dpix(48), dpix(120))
        self.setMouseTracking(True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(dpix(6), dpix(8), dpix(6), dpix(8))
        self.slider = QSlider(Qt.Orientation.Vertical)
        self.slider.setObjectName('volumePopupSlider')
        self.slider.setRange(0, 100)
        self.slider.setValue(DEFAULT_VOLUME)
        layout.addWidget(self.slider)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(_VOLUME_POPUP_HIDE_MS)
        self._hide_timer.timeout.connect(self.hide)
        self.apply_theme(ThemeManager.instance().palette)

    def apply_theme(self, palette):
        pal = self.palette()
        bg = QColor(palette.bg_primary)
        bg.setAlpha(230)
        pal.setColor(QPalette.ColorRole.Window, bg)
        self.setPalette(pal)
        self.setStyleSheet(_build_volume_popup_style(palette))

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
        self.setMouseTracking(True)
        self._setup_ui()
        self.apply_theme(ThemeManager.instance().palette)

    def apply_theme(self, palette):
        p = self.palette()
        bg = QColor(palette.bg_primary)
        bg.setAlpha(200)
        p.setColor(QPalette.ColorRole.Window, bg)
        self.setPalette(p)
        self.setStyleSheet(_build_control_style(palette))
        self.volume_popup.apply_theme(palette)
        self.btn_play.update()
        self.btn_volume.update()

    def _setup_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(dpix(8), dpix(2), dpix(8), dpix(0))

        self.btn_play = _MediaButton('play', padding=0.33)
        layout.addWidget(self.btn_play)

        layout.addSpacing(dpix(2))

        self.seek_slider = QSlider(Qt.Orientation.Horizontal)
        self.seek_slider.setObjectName('seekSlider')
        self.seek_slider.setRange(0, 1000)
        layout.addWidget(self.seek_slider, 1)

        layout.addSpacing(dpix(5))

        self.time_label = QLabel('00:00 / 00:00')
        layout.addWidget(self.time_label)

        layout.addSpacing(dpix(2))

        self.btn_volume = _MediaButton('volume', padding=0.28)
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
        self._volume = DEFAULT_VOLUME
        self._muted = False
        self._speed = 1.0
        self._cover_mode = False
        self._looping = False
        self._pause_in_background = False
        self._paused_by_background = False
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
        Command.set_checked("vview.toggle_mute", self._muted)
        Command.set_checked("vview.toggle_fit_mode", self._cover_mode)
        Command.set_checked("vview.toggle_loop", self._looping)
        Command.set_checked("vview.toggle_pause_in_background", self._pause_in_background)

        ThemeManager.instance().on_theme_changed.connect(self._on_theme_changed)
        app = QApplication.instance()
        if app:
            app.applicationStateChanged.connect(self._on_app_state_changed)

    def _on_theme_changed(self, palette):
        self._control_bar.apply_theme(palette)

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

    def toggle_mute(self):
        self._muted = not self._muted
        if self._player:
            self._player.mute = self._muted
        self._update_volume_icon()
        Command.set_checked("vview.toggle_mute", self._muted)

    def set_muted(self, muted: bool):
        self._muted = muted
        if self._player:
            self._player.mute = self._muted
        self._update_volume_icon()
        Command.set_checked("vview.toggle_mute", self._muted)

    def set_speed(self, speed):
        self._speed = max(0.25, min(3.0, float(speed)))
        if self._player:
            self._player.speed = self._speed

    def toggle_fit_mode(self):
        self._cover_mode = not self._cover_mode
        if self._player:
            self._player['panscan'] = 1.0 if self._cover_mode else 0.0
        Command.set_checked("vview.toggle_fit_mode", self._cover_mode)

    def set_cover_mode(self, cover: bool):
        self._cover_mode = cover
        if self._player:
            self._player['panscan'] = 1.0 if self._cover_mode else 0.0
        Command.set_checked("vview.toggle_fit_mode", self._cover_mode)

    def toggle_loop(self):
        self._looping = not self._looping
        if self._player:
            self._player['loop-file'] = 'inf' if self._looping else 'no'
        Command.set_checked("vview.toggle_loop", self._looping)

    def set_looping(self, looping: bool):
        self._looping = looping
        if self._player:
            self._player['loop-file'] = 'inf' if self._looping else 'no'
        Command.set_checked("vview.toggle_loop", self._looping)

    def toggle_pause_in_background(self):
        self._pause_in_background = not self._pause_in_background
        Command.set_checked("vview.toggle_pause_in_background", self._pause_in_background)

    def set_pause_in_background(self, enabled: bool):
        self._pause_in_background = enabled
        Command.set_checked("vview.toggle_pause_in_background", self._pause_in_background)

    def _on_volume_changed(self, value):
        self._volume = value
        if self._muted and value > 0:
            self._muted = False
            if self._player:
                self._player.mute = False
            Command.set_checked("vview.toggle_mute", False)
        if self._player:
            self._player.volume = value
        self._update_volume_icon()

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
        s = event.size()
        w, h = s.width(), s.height()
        self._player_area.setGeometry(0, 0, w, h)
        bar_h = dpix(_CONTROL_BAR_HEIGHT)
        self._control_bar.setGeometry(0, h - bar_h, w, bar_h)
        if self._controls_visible:
            self._control_bar.raise_()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._hide_controls()

    def _on_app_state_changed(self, state):
        if state != Qt.ApplicationState.ApplicationActive:
            if self._pause_in_background and self._player and not self._player.pause:
                self._paused_by_background = True
                self._player.pause = True
                self._update_play_button()
        else:
            if self._paused_by_background and self._player and self._path:
                self._paused_by_background = False
                self._player.pause = False
                self._update_play_button()

    def cleanup(self):
        self._pos_timer.stop()
        self._hide_timer.stop()
        self._control_bar.volume_popup.hide()
        if self._player:
            self._player.terminate()
            self._player = None
