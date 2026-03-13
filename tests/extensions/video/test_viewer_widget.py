import pytest
from unittest.mock import MagicMock, patch, PropertyMock, call
from PySide6 import QtCore, QtWidgets


@pytest.fixture(autouse=True)
def _patch_mpv_viewer(monkeypatch):
    import sys
    mock = MagicMock()
    monkeypatch.setitem(sys.modules, 'mpv', mock)
    from extensions.video.viewer_widget import VideoViewerWidget
    monkeypatch.setattr(VideoViewerWidget, '_mpv_mod', mock)
    monkeypatch.setattr(VideoViewerWidget, '_mpv_checked', True)
    yield mock


@pytest.fixture(autouse=True)
def _patch_command(monkeypatch):
    monkeypatch.setattr(
        "extensions.video.viewer_widget.Command",
        MagicMock(),
    )


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
        assert w._muted is False
        assert w._cover_mode is False
        assert w._looping is False
        w.cleanup()

    def test_init_syncs_default_checked_states(self, qtbot, _patch_command):
        from extensions.video.viewer_widget import VideoViewerWidget, Command
        Command.reset_mock()
        w = VideoViewerWidget()
        calls = Command.set_checked.call_args_list
        synced = {c.args[0]: c.args[1] for c in calls}
        assert synced["vview.toggle_mute"] is False
        assert synced["vview.toggle_fit_mode"] is False
        assert synced["vview.toggle_loop"] is False
        w.cleanup()


class TestVideoViewerWidgetLoad:
    def test_load_sets_path(self, qtbot, _patch_mpv_viewer):
        from extensions.video.viewer_widget import VideoViewerWidget
        w = VideoViewerWidget()
        _patch_mpv_viewer.MPV.return_value = MagicMock()
        w.load('/test.mp4')
        assert w._path == '/test.mp4'
        w.cleanup()

    def test_load_creates_player(self, qtbot, _patch_mpv_viewer):
        from extensions.video.viewer_widget import VideoViewerWidget
        w = VideoViewerWidget()
        mock_player = MagicMock()
        _patch_mpv_viewer.MPV.return_value = mock_player
        w.load('/test.mp4')
        assert w._player is mock_player
        mock_player.play.assert_called_once_with('/test.mp4')
        w.cleanup()

    def test_load_starts_pos_timer(self, qtbot, _patch_mpv_viewer):
        from extensions.video.viewer_widget import VideoViewerWidget
        w = VideoViewerWidget()
        _patch_mpv_viewer.MPV.return_value = MagicMock()
        w.load('/test.mp4')
        assert w._pos_timer.isActive()
        w.cleanup()


class TestVideoViewerWidgetClear:
    def test_clear_stops_player(self, qtbot, _patch_mpv_viewer):
        from extensions.video.viewer_widget import VideoViewerWidget
        w = VideoViewerWidget()
        mock_player = MagicMock()
        _patch_mpv_viewer.MPV.return_value = mock_player
        w.load('/test.mp4')
        w.clear()
        mock_player.command.assert_called_with('stop')
        assert w._path is None
        w.cleanup()

    def test_clear_stops_timer(self, qtbot, _patch_mpv_viewer):
        from extensions.video.viewer_widget import VideoViewerWidget
        w = VideoViewerWidget()
        _patch_mpv_viewer.MPV.return_value = MagicMock()
        w.load('/test.mp4')
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
        w.load('/test.mp4')
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
        assert w._muted is True
        assert player.mute is True
        w.toggle_mute()
        assert w._muted is False
        assert player.mute is False
        w.cleanup()

    def test_volume_change_unmutes(self, qtbot, _patch_mpv_viewer):
        w, player = self._make_widget(qtbot, _patch_mpv_viewer)
        w.toggle_mute()
        assert w._muted is True
        w._on_volume_changed(50)
        assert w._muted is False
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
        assert w._cover_mode is False
        w.toggle_fit_mode()
        assert w._cover_mode is True
        assert player.__setitem__.call_args_list[-1] == (('panscan', 1.0),)
        w.cleanup()

    def test_toggle_loop(self, qtbot, _patch_mpv_viewer):
        w, player = self._make_widget(qtbot, _patch_mpv_viewer)
        assert w._looping is False
        w.toggle_loop()
        assert w._looping is True
        assert player.__setitem__.call_args_list[-1] == (('loop-file', 'inf'),)
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
        assert '00:00' in bar.time_label.text()

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
        btn = _MediaButton('play')
        assert btn._icon_key == 'play'

    def test_set_icon_key(self, qtbot):
        from extensions.video.viewer_widget import _MediaButton
        btn = _MediaButton('play')
        btn.set_icon_key('pause')
        assert btn._icon_key == 'pause'


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
        assert _format_time(0) == '00:00'

    def test_seconds(self):
        from extensions.video.viewer_widget import _format_time
        assert _format_time(65) == '01:05'

    def test_hours(self):
        from extensions.video.viewer_widget import _format_time
        assert _format_time(3661) == '1:01:01'

    def test_none(self):
        from extensions.video.viewer_widget import _format_time
        assert _format_time(None) == '00:00'

    def test_negative(self):
        from extensions.video.viewer_widget import _format_time
        assert _format_time(-5) == '00:00'


class TestVideoViewerWidgetDefaultState:
    def test_default_volume_uses_constant(self, qtbot):
        from extensions.video.viewer_widget import VideoViewerWidget, DEFAULT_VOLUME
        w = VideoViewerWidget()
        assert w._volume == DEFAULT_VOLUME
        w.cleanup()

    def test_default_muted_false(self, qtbot):
        from extensions.video.viewer_widget import VideoViewerWidget
        w = VideoViewerWidget()
        assert w._muted is False
        w.cleanup()
