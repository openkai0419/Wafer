import pytest
from unittest.mock import MagicMock, patch, PropertyMock, call
from PySide6 import QtCore, QtWidgets


@pytest.fixture(autouse=True)
def _patch_mpv_viewer(monkeypatch):
    import sys

    mock = MagicMock()
    monkeypatch.setitem(sys.modules, "mpv", mock)
    from extensions.video.viewer_widget import VideoViewerWidget

    monkeypatch.setattr(VideoViewerWidget, "_mpv_mod", mock)
    monkeypatch.setattr(VideoViewerWidget, "_mpv_checked", True)
    yield mock


@pytest.fixture(autouse=True)
def _patch_binding(monkeypatch):
    monkeypatch.setattr(
        "extensions.video.viewer_widget.ActionKit.UIMixin.init_command_binding",
        lambda self, *a, **kw: None,
    )


class TestVideoViewerWidgetInit:
    def test_creates_player_area(self, qtbot):
        from extensions.video.viewer_widget import VideoViewerWidget

        w = VideoViewerWidget()
        assert w._player_area is not None
        assert w._player_area.testAttribute(QtCore.Qt.WidgetAttribute.WA_NativeWindow)
        w.cleanup()

    def test_creates_control_bar(self, qtbot):
        from extensions.video.viewer_widget import VideoViewerWidget, VideoControlBar

        w = VideoViewerWidget()
        assert isinstance(w._control_bar, VideoControlBar)
        assert not w._control_bar.isVisible()
        w.cleanup()

    def test_initial_state(self, qtbot):
        from extensions.video.viewer_widget import VideoViewerWidget, DEFAULT_VOLUME

        w = VideoViewerWidget()
        assert w._path is None
        assert w._player is None
        assert w._volume == DEFAULT_VOLUME
        assert w.muted is False
        assert w.cover_mode is False
        assert w.looping is True
        assert w.pause_in_background is False
        w.cleanup()


class TestVideoViewerWidgetLoad:
    def test_load_sets_path(self, qtbot, _patch_mpv_viewer):
        from extensions.video.viewer_widget import VideoViewerWidget

        w = VideoViewerWidget()
        _patch_mpv_viewer.MPV.return_value = MagicMock()
        w.load("/test.mp4")
        assert w._path == "/test.mp4"
        w.cleanup()

    def test_load_creates_player(self, qtbot, _patch_mpv_viewer):
        from extensions.video.viewer_widget import VideoViewerWidget

        w = VideoViewerWidget()
        mock_player = MagicMock()
        _patch_mpv_viewer.MPV.return_value = mock_player
        w.load("/test.mp4")
        assert w._player is mock_player
        mock_player.play.assert_called_once_with("/test.mp4")
        w.cleanup()

    def test_load_starts_pos_timer(self, qtbot, _patch_mpv_viewer):
        from extensions.video.viewer_widget import VideoViewerWidget

        w = VideoViewerWidget()
        _patch_mpv_viewer.MPV.return_value = MagicMock()
        w.load("/test.mp4")
        assert w._pos_timer.isActive()
        w.cleanup()


class TestVideoViewerWidgetClear:
    def test_clear_stops_player(self, qtbot, _patch_mpv_viewer):
        from extensions.video.viewer_widget import VideoViewerWidget

        w = VideoViewerWidget()
        mock_player = MagicMock()
        _patch_mpv_viewer.MPV.return_value = mock_player
        w.load("/test.mp4")
        w.clear()
        mock_player.command.assert_called_with("stop")
        assert w._path is None
        w.cleanup()

    def test_clear_stops_timer(self, qtbot, _patch_mpv_viewer):
        from extensions.video.viewer_widget import VideoViewerWidget

        w = VideoViewerWidget()
        _patch_mpv_viewer.MPV.return_value = MagicMock()
        w.load("/test.mp4")
        w.clear()
        assert not w._pos_timer.isActive()
        w.cleanup()


class TestVideoViewerWidgetControls:
    def _make_widget(self, qtbot, mock_mpv):
        from extensions.video.viewer_widget import VideoViewerWidget

        w = VideoViewerWidget()
        mock_player = MagicMock()
        mock_player.pause = False
        mock_mpv.MPV.return_value = mock_player
        w.load("/test.mp4")
        return w, mock_player

    def test_toggle_pause(self, qtbot, _patch_mpv_viewer):
        w, player = self._make_widget(qtbot, _patch_mpv_viewer)
        w.toggle_pause()
        assert player.pause is True
        w.cleanup()

    def test_seek_forward(self, qtbot, _patch_mpv_viewer):
        w, player = self._make_widget(qtbot, _patch_mpv_viewer)
        w.seek(10)
        player.seek.assert_called_once_with(10)
        w.cleanup()

    def test_seek_backward(self, qtbot, _patch_mpv_viewer):
        w, player = self._make_widget(qtbot, _patch_mpv_viewer)
        w.seek(-10)
        player.seek.assert_called_once_with(-10)
        w.cleanup()

    def test_frame_step(self, qtbot, _patch_mpv_viewer):
        w, player = self._make_widget(qtbot, _patch_mpv_viewer)
        w.frame_step()
        player.frame_step.assert_called_once()
        w.cleanup()

    def test_frame_back_step(self, qtbot, _patch_mpv_viewer):
        w, player = self._make_widget(qtbot, _patch_mpv_viewer)
        w.frame_back_step()
        player.frame_back_step.assert_called_once()
        w.cleanup()

    def test_set_volume(self, qtbot, _patch_mpv_viewer):
        w, player = self._make_widget(qtbot, _patch_mpv_viewer)
        w.set_volume(75)
        assert w._volume == 75
        assert player.volume == 75
        assert w._control_bar.volume_slider.value() == 75
        w.cleanup()

    def test_set_volume_clamps(self, qtbot, _patch_mpv_viewer):
        w, _ = self._make_widget(qtbot, _patch_mpv_viewer)
        w.set_volume(150)
        assert w._volume == 100
        w.set_volume(-10)
        assert w._volume == 0
        w.cleanup()

    def test_toggle_mute(self, qtbot, _patch_mpv_viewer):
        w, player = self._make_widget(qtbot, _patch_mpv_viewer)
        w.toggle_mute()
        assert w.muted is True
        assert player.mute is True
        w.toggle_mute()
        assert w.muted is False
        assert player.mute is False
        w.cleanup()

    def test_volume_change_unmutes(self, qtbot, _patch_mpv_viewer):
        w, player = self._make_widget(qtbot, _patch_mpv_viewer)
        w.toggle_mute()
        assert w.muted is True
        w._on_volume_changed(50)
        assert w.muted is False
        assert player.mute is False
        assert w._volume == 50
        w.cleanup()

    def test_set_speed(self, qtbot, _patch_mpv_viewer):
        w, player = self._make_widget(qtbot, _patch_mpv_viewer)
        w.set_speed(2.0)
        assert w._speed == 2.0
        assert player.speed == 2.0
        w.cleanup()

    def test_set_speed_clamps(self, qtbot, _patch_mpv_viewer):
        w, _ = self._make_widget(qtbot, _patch_mpv_viewer)
        w.set_speed(0.1)
        assert w._speed == 0.25
        w.set_speed(5.0)
        assert w._speed == 3.0
        w.cleanup()

    def test_toggle_fit_mode(self, qtbot, _patch_mpv_viewer):
        w, player = self._make_widget(qtbot, _patch_mpv_viewer)
        assert w.cover_mode is False
        w.toggle_fit_mode()
        assert w.cover_mode is True
        assert player.__setitem__.call_args_list[-1] == (("panscan", 1.0),)
        w.cleanup()

    def test_toggle_loop(self, qtbot, _patch_mpv_viewer):
        w, player = self._make_widget(qtbot, _patch_mpv_viewer)
        assert w.looping is True
        w.toggle_loop()
        assert w.looping is False
        assert player.__setitem__.call_args_list[-1] == (("loop-file", "no"),)
        w.cleanup()

    def test_toggle_pause_in_background(self, qtbot, _patch_mpv_viewer):
        w, player = self._make_widget(qtbot, _patch_mpv_viewer)
        assert w.pause_in_background is False
        w.toggle_pause_in_background()
        assert w.pause_in_background is True
        w.toggle_pause_in_background()
        assert w.pause_in_background is False
        w.cleanup()

    def test_background_pauses_when_enabled(self, qtbot, _patch_mpv_viewer):
        w, player = self._make_widget(qtbot, _patch_mpv_viewer)
        w.set_pause_in_background(True)
        player.pause = False
        w._on_app_state_changed(QtCore.Qt.ApplicationState.ApplicationInactive)
        assert player.pause is True
        assert w._paused_by_background is True
        w.cleanup()

    def test_background_does_not_pause_when_disabled(self, qtbot, _patch_mpv_viewer):
        w, player = self._make_widget(qtbot, _patch_mpv_viewer)
        assert w.pause_in_background is False
        player.pause = False
        w._on_app_state_changed(QtCore.Qt.ApplicationState.ApplicationInactive)
        assert player.pause is False
        assert w._paused_by_background is False
        w.cleanup()

    def test_foreground_resumes_after_background(self, qtbot, _patch_mpv_viewer):
        w, player = self._make_widget(qtbot, _patch_mpv_viewer)
        w.set_pause_in_background(True)
        player.pause = False
        w._on_app_state_changed(QtCore.Qt.ApplicationState.ApplicationInactive)
        assert player.pause is True
        w._on_app_state_changed(QtCore.Qt.ApplicationState.ApplicationActive)
        assert player.pause is False
        assert w._paused_by_background is False
        w.cleanup()

    def test_foreground_does_not_resume_if_manually_paused(self, qtbot, _patch_mpv_viewer):
        w, player = self._make_widget(qtbot, _patch_mpv_viewer)
        player.pause = True
        w._on_app_state_changed(QtCore.Qt.ApplicationState.ApplicationInactive)
        assert w._paused_by_background is False
        w._on_app_state_changed(QtCore.Qt.ApplicationState.ApplicationActive)
        assert player.pause is True
        w.cleanup()


class TestVideoViewerWidgetControlBarVisibility:
    def test_show_controls(self, qtbot):
        from extensions.video.viewer_widget import VideoViewerWidget

        w = VideoViewerWidget()
        assert not w._controls_visible
        w._show_controls()
        assert w._controls_visible
        assert not w._control_bar.isHidden()
        w.cleanup()

    def test_hide_controls(self, qtbot):
        from extensions.video.viewer_widget import VideoViewerWidget

        w = VideoViewerWidget()
        w._show_controls()
        w._hide_controls()
        assert not w._controls_visible
        assert w._control_bar.isHidden()
        w.cleanup()

    def test_control_enter_stops_hide_timer(self, qtbot):
        from extensions.video.viewer_widget import VideoViewerWidget

        w = VideoViewerWidget()
        w._show_controls()
        assert w._hide_timer.isActive()
        w._on_control_enter()
        assert not w._hide_timer.isActive()
        w.cleanup()


class TestVideoViewerWidgetNoPlayer:
    def test_toggle_pause_noop(self, qtbot):
        from extensions.video.viewer_widget import VideoViewerWidget

        w = VideoViewerWidget()
        w.toggle_pause()
        w.cleanup()

    def test_seek_noop(self, qtbot):
        from extensions.video.viewer_widget import VideoViewerWidget

        w = VideoViewerWidget()
        w.seek(10)
        w.cleanup()

    def test_frame_step_noop(self, qtbot):
        from extensions.video.viewer_widget import VideoViewerWidget

        w = VideoViewerWidget()
        w.frame_step()
        w.cleanup()

    def test_clear_noop(self, qtbot):
        from extensions.video.viewer_widget import VideoViewerWidget

        w = VideoViewerWidget()
        w.clear()
        w.cleanup()


class TestVideoControlBar:
    def test_has_seek_slider(self, qtbot):
        from extensions.video.viewer_widget import VideoControlBar

        bar = VideoControlBar()
        assert bar.seek_slider is not None
        assert bar.seek_slider.maximum() == 1000

    def test_has_volume_slider_in_popup(self, qtbot):
        from extensions.video.viewer_widget import VideoControlBar

        bar = VideoControlBar()
        assert bar.volume_slider is not None
        assert bar.volume_slider.maximum() == 100

    def test_has_play_button(self, qtbot):
        from extensions.video.viewer_widget import VideoControlBar, _MediaButton

        bar = VideoControlBar()
        assert bar.btn_play is not None
        assert isinstance(bar.btn_play, _MediaButton)

    def test_has_volume_button(self, qtbot):
        from extensions.video.viewer_widget import VideoControlBar, _MediaButton

        bar = VideoControlBar()
        assert bar.btn_volume is not None
        assert isinstance(bar.btn_volume, _MediaButton)

    def test_has_time_label(self, qtbot):
        from extensions.video.viewer_widget import VideoControlBar

        bar = VideoControlBar()
        assert bar.time_label is not None
        assert "00:00" in bar.time_label.text()

    def test_native_window_attribute(self, qtbot):
        from extensions.video.viewer_widget import VideoControlBar

        bar = VideoControlBar()
        assert bar.testAttribute(QtCore.Qt.WidgetAttribute.WA_NativeWindow)

    def test_single_row_layout(self, qtbot):
        from extensions.video.viewer_widget import VideoControlBar

        bar = VideoControlBar()
        layout = bar.layout()
        assert isinstance(layout, QtWidgets.QHBoxLayout)


class TestMediaButton:
    def test_icon_key_play(self, qtbot):
        from extensions.video.viewer_widget import _MediaButton

        btn = _MediaButton("play")
        assert btn._icon_key == "play"

    def test_set_icon_key(self, qtbot):
        from extensions.video.viewer_widget import _MediaButton

        btn = _MediaButton("play")
        btn.set_icon_key("pause")
        assert btn._icon_key == "pause"


class TestVolumePopup:
    def test_has_slider(self, qtbot):
        from extensions.video.viewer_widget import VolumePopup

        popup = VolumePopup()
        assert popup.slider is not None
        assert popup.slider.orientation() == QtCore.Qt.Orientation.Vertical
        assert popup.slider.maximum() == 100
        popup.close()

    def test_initially_hidden(self, qtbot):
        from extensions.video.viewer_widget import VolumePopup

        popup = VolumePopup()
        assert not popup.isVisible()
        popup.close()


class TestFormatTime:
    def test_zero(self):
        from extensions.video.viewer_widget import _format_time

        assert _format_time(0) == "00:00"

    def test_seconds(self):
        from extensions.video.viewer_widget import _format_time

        assert _format_time(65) == "01:05"

    def test_hours(self):
        from extensions.video.viewer_widget import _format_time

        assert _format_time(3661) == "1:01:01"

    def test_none(self):
        from extensions.video.viewer_widget import _format_time

        assert _format_time(None) == "00:00"

    def test_negative(self):
        from extensions.video.viewer_widget import _format_time

        assert _format_time(-5) == "00:00"


class TestVideoViewerWidgetDefaultState:
    def test_default_volume_uses_constant(self, qtbot):
        from extensions.video.viewer_widget import VideoViewerWidget, DEFAULT_VOLUME

        w = VideoViewerWidget()
        assert w._volume == DEFAULT_VOLUME
        w.cleanup()

    def test_default_muted_false(self, qtbot):
        from extensions.video.viewer_widget import VideoViewerWidget

        w = VideoViewerWidget()
        assert w.muted is False
        w.cleanup()


class TestThemeIntegration:
    def test_control_bar_uses_palette_bg(self, qtbot):
        from extensions.video.viewer_widget import VideoControlBar
        from wafer.core.color.theme import ThemeManager

        bar = VideoControlBar()
        palette = ThemeManager.instance().palette
        bg = bar.palette().color(QtWidgets.QWidget().backgroundRole())
        from PySide6.QtGui import QColor

        expected = QColor(palette.bg_primary)
        expected.setAlpha(200)
        assert bg.red() == expected.red()
        assert bg.green() == expected.green()
        assert bg.blue() == expected.blue()

    def test_apply_theme_updates_stylesheet(self, qtbot):
        from extensions.video.viewer_widget import VideoControlBar
        from wafer.core.color.theme_palette import DARK, LIGHT

        bar = VideoControlBar()
        bar.apply_theme(LIGHT)
        style = bar.styleSheet()
        assert LIGHT.accent in style
        assert LIGHT.border_default in style
        bar.apply_theme(DARK)
        style = bar.styleSheet()
        assert DARK.accent in style

    def test_volume_popup_theme_applied(self, qtbot):
        from extensions.video.viewer_widget import VolumePopup
        from wafer.core.color.theme_palette import LIGHT

        popup = VolumePopup()
        popup.apply_theme(LIGHT)
        style = popup.styleSheet()
        assert LIGHT.accent in style
        popup.close()

    def test_theme_change_propagates_to_control_bar(self, qtbot):
        from extensions.video.viewer_widget import VideoViewerWidget
        from wafer.core.color.theme import ThemeManager
        from wafer.core.color.theme_palette import LIGHT, DARK

        w = VideoViewerWidget()
        tm = ThemeManager.instance()
        tm.set_light()
        style = w._control_bar.styleSheet()
        assert LIGHT.accent in style
        tm.set_dark()
        style = w._control_bar.styleSheet()
        assert DARK.accent in style
        w.cleanup()


class TestAutoplayObserver:
    def _make_widget(self, qtbot, mock_mpv):
        from extensions.video.viewer_widget import VideoViewerWidget

        w = VideoViewerWidget()
        mock_player = MagicMock()
        mock_player.pause = False
        mock_player.duration = 10.0
        mock_mpv.MPV.return_value = mock_player
        w.load("/test.mp4")
        return w, mock_player

    def test_ensure_player_registers_observers(self, qtbot, _patch_mpv_viewer):
        w, player = self._make_widget(qtbot, _patch_mpv_viewer)
        observe_calls = {c.args[0] for c in player.observe_property.call_args_list}
        assert "time-pos" in observe_calls
        assert "eof-reached" in observe_calls
        w.cleanup()

    def test_eof_observer_fires_advance_when_not_looping(self, qtbot, _patch_mpv_viewer):
        w, player = self._make_widget(qtbot, _patch_mpv_viewer)
        called = []
        w._autoplay_advance = lambda: called.append(True)
        w.looping = False
        w._on_mpv_eof("eof-reached", True)
        from PySide6.QtWidgets import QApplication

        QApplication.processEvents()
        assert len(called) == 1
        assert w._autoplay_advance is None
        w.cleanup()

    def test_eof_observer_ignored_when_looping(self, qtbot, _patch_mpv_viewer):
        w, player = self._make_widget(qtbot, _patch_mpv_viewer)
        called = []
        w._autoplay_advance = lambda: called.append(True)
        w.looping = True
        w._on_mpv_eof("eof-reached", True)
        from PySide6.QtWidgets import QApplication

        QApplication.processEvents()
        assert len(called) == 0
        assert w._autoplay_advance is not None
        w.cleanup()

    def test_eof_observer_ignored_when_no_advance(self, qtbot, _patch_mpv_viewer):
        w, player = self._make_widget(qtbot, _patch_mpv_viewer)
        w._autoplay_advance = None
        w.looping = False
        w._on_mpv_eof("eof-reached", True)
        from PySide6.QtWidgets import QApplication

        QApplication.processEvents()
        w.cleanup()

    def test_eof_observer_ignored_when_value_false(self, qtbot, _patch_mpv_viewer):
        w, player = self._make_widget(qtbot, _patch_mpv_viewer)
        called = []
        w._autoplay_advance = lambda: called.append(True)
        w.looping = False
        w._on_mpv_eof("eof-reached", False)
        from PySide6.QtWidgets import QApplication

        QApplication.processEvents()
        assert len(called) == 0
        w.cleanup()

    def test_time_pos_wraparound_fires_advance_when_looping(self, qtbot, _patch_mpv_viewer):
        w, player = self._make_widget(qtbot, _patch_mpv_viewer)
        called = []
        w._autoplay_advance = lambda: called.append(True)
        w.looping = True
        player.duration = 10.0
        w._prev_time_pos = 9.0
        w._on_mpv_time_pos("time-pos", 0.5)
        from PySide6.QtWidgets import QApplication

        QApplication.processEvents()
        assert len(called) == 1
        assert w._autoplay_advance is None
        w.cleanup()

    def test_time_pos_no_wraparound_no_advance(self, qtbot, _patch_mpv_viewer):
        w, player = self._make_widget(qtbot, _patch_mpv_viewer)
        called = []
        w._autoplay_advance = lambda: called.append(True)
        w.looping = True
        player.duration = 10.0
        w._prev_time_pos = 3.0
        w._on_mpv_time_pos("time-pos", 4.0)
        from PySide6.QtWidgets import QApplication

        QApplication.processEvents()
        assert len(called) == 0
        assert w._autoplay_advance is not None
        w.cleanup()

    def test_time_pos_not_looping_only_tracks(self, qtbot, _patch_mpv_viewer):
        w, player = self._make_widget(qtbot, _patch_mpv_viewer)
        called = []
        w._autoplay_advance = lambda: called.append(True)
        w.looping = False
        w._prev_time_pos = 9.0
        w._on_mpv_time_pos("time-pos", 0.5)
        from PySide6.QtWidgets import QApplication

        QApplication.processEvents()
        assert len(called) == 0
        assert w._prev_time_pos == 0.5
        w.cleanup()

    def test_load_resets_prev_time_pos(self, qtbot, _patch_mpv_viewer):
        w, player = self._make_widget(qtbot, _patch_mpv_viewer)
        w._prev_time_pos = 5.0
        w.load("/test2.mp4")
        assert w._prev_time_pos is None
        w.cleanup()

    def test_clear_resets_prev_time_pos(self, qtbot, _patch_mpv_viewer):
        w, player = self._make_widget(qtbot, _patch_mpv_viewer)
        w._prev_time_pos = 5.0
        w.clear()
        assert w._prev_time_pos is None
        w.cleanup()

    def test_fire_autoplay_advance_only_once(self, qtbot, _patch_mpv_viewer):
        w, player = self._make_widget(qtbot, _patch_mpv_viewer)
        called = []
        w._autoplay_advance = lambda: called.append(True)
        w._fire_autoplay_advance()
        w._fire_autoplay_advance()
        assert len(called) == 1
        w.cleanup()

    def test_deactivate_clears_autoplay(self, qtbot, _patch_mpv_viewer):
        w, player = self._make_widget(qtbot, _patch_mpv_viewer)
        w._autoplay_advance = lambda: None
        w.deactivate()
        assert w._autoplay_advance is None
        w.cleanup()

    def test_set_autoplay_advance_fires_immediately_on_eof(self, qtbot, _patch_mpv_viewer):
        w, player = self._make_widget(qtbot, _patch_mpv_viewer)
        player.eof_reached = True
        w.looping = False
        called = []
        w.set_autoplay_advance(lambda: called.append(True))
        from PySide6.QtWidgets import QApplication

        QApplication.processEvents()
        assert len(called) == 1
        assert w._autoplay_advance is None
        w.cleanup()

    def test_set_autoplay_advance_no_fire_when_not_eof(self, qtbot, _patch_mpv_viewer):
        w, player = self._make_widget(qtbot, _patch_mpv_viewer)
        player.eof_reached = False
        w.looping = False
        called = []
        w.set_autoplay_advance(lambda: called.append(True))
        from PySide6.QtWidgets import QApplication

        QApplication.processEvents()
        assert len(called) == 0
        assert w._autoplay_advance is not None
        w.cleanup()

    def test_set_autoplay_advance_no_fire_when_looping(self, qtbot, _patch_mpv_viewer):
        w, player = self._make_widget(qtbot, _patch_mpv_viewer)
        player.eof_reached = True
        w.looping = True
        called = []
        w.set_autoplay_advance(lambda: called.append(True))
        from PySide6.QtWidgets import QApplication

        QApplication.processEvents()
        assert len(called) == 0
        assert w._autoplay_advance is not None
        w.cleanup()
