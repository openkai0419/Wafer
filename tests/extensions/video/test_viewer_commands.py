import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture(autouse=True)
def _suppress_notifier(monkeypatch):
    monkeypatch.setattr(
        "wafer.core.commands.command.require.Notifier",
        type("FakeNotifier", (), {"warning": staticmethod(lambda msg: None)}),
    )


def _make_ctx(vw=None):
    ctx = MagicMock()
    ctx.get_instance = MagicMock(return_value=vw)
    return ctx


class TestTogglePause:
    def test_calls_toggle_pause(self):
        from extensions.video.viewer_commands import toggle_pause
        vw = MagicMock()
        ctx = _make_ctx(vw)
        toggle_pause(ctx)
        vw.toggle_pause.assert_called_once()

    def test_noop_without_instance(self):
        from extensions.video.viewer_commands import toggle_pause
        ctx = _make_ctx(None)
        result = toggle_pause(ctx)
        assert result is None


class TestSeekForward:
    def test_calls_seek_positive(self):
        from extensions.video.viewer_commands import seek_forward
        vw = MagicMock()
        ctx = _make_ctx(vw)
        seek_forward(ctx, seconds=10)
        vw.seek.assert_called_once_with(10)

    def test_custom_seconds(self):
        from extensions.video.viewer_commands import seek_forward
        vw = MagicMock()
        ctx = _make_ctx(vw)
        seek_forward(ctx, seconds=30)
        vw.seek.assert_called_once_with(30)


class TestSeekBackward:
    def test_calls_seek_negative(self):
        from extensions.video.viewer_commands import seek_backward
        vw = MagicMock()
        ctx = _make_ctx(vw)
        seek_backward(ctx, seconds=10)
        vw.seek.assert_called_once_with(-10)


class TestFrameStep:
    def test_calls_frame_step(self):
        from extensions.video.viewer_commands import frame_step
        vw = MagicMock()
        ctx = _make_ctx(vw)
        frame_step(ctx)
        vw.frame_step.assert_called_once()


class TestFrameBackStep:
    def test_calls_frame_back_step(self):
        from extensions.video.viewer_commands import frame_back_step
        vw = MagicMock()
        ctx = _make_ctx(vw)
        frame_back_step(ctx)
        vw.frame_back_step.assert_called_once()


class TestVolumeUp:
    def test_calls_set_volume_with_increase(self):
        from extensions.video.viewer_commands import volume_up
        vw = MagicMock()
        vw._volume = 50
        ctx = _make_ctx(vw)
        volume_up(ctx, step=5)
        vw.set_volume.assert_called_once_with(55)

    def test_custom_step(self):
        from extensions.video.viewer_commands import volume_up
        vw = MagicMock()
        vw._volume = 80
        ctx = _make_ctx(vw)
        volume_up(ctx, step=10)
        vw.set_volume.assert_called_once_with(90)


class TestVolumeDown:
    def test_calls_set_volume_with_decrease(self):
        from extensions.video.viewer_commands import volume_down
        vw = MagicMock()
        vw._volume = 50
        ctx = _make_ctx(vw)
        volume_down(ctx, step=5)
        vw.set_volume.assert_called_once_with(45)

    def test_custom_step(self):
        from extensions.video.viewer_commands import volume_down
        vw = MagicMock()
        vw._volume = 10
        ctx = _make_ctx(vw)
        volume_down(ctx, step=15)
        vw.set_volume.assert_called_once_with(-5)


class TestToggleMute:
    def test_calls_toggle_mute(self):
        from extensions.video.viewer_commands import toggle_mute
        vw = MagicMock()
        ctx = _make_ctx(vw)
        toggle_mute(ctx)
        vw.toggle_mute.assert_called_once()


class TestToggleFitMode:
    def test_calls_toggle_fit_mode(self):
        from extensions.video.viewer_commands import toggle_fit_mode
        vw = MagicMock()
        ctx = _make_ctx(vw)
        toggle_fit_mode(ctx)
        vw.toggle_fit_mode.assert_called_once()


class TestSpeedUp:
    def test_calls_set_speed_with_increase(self):
        from extensions.video.viewer_commands import speed_up
        vw = MagicMock()
        vw._speed = 1.0
        ctx = _make_ctx(vw)
        speed_up(ctx, step=0.25)
        vw.set_speed.assert_called_once_with(1.25)


class TestSpeedDown:
    def test_calls_set_speed_with_decrease(self):
        from extensions.video.viewer_commands import speed_down
        vw = MagicMock()
        vw._speed = 1.0
        ctx = _make_ctx(vw)
        speed_down(ctx, step=0.25)
        vw.set_speed.assert_called_once_with(0.75)


class TestSetSpeed:
    def test_calls_set_speed(self):
        from extensions.video.viewer_commands import set_speed
        vw = MagicMock()
        ctx = _make_ctx(vw)
        set_speed(ctx, speed=2.0)
        vw.set_speed.assert_called_once_with(2.0)


class TestToggleLoop:
    def test_calls_toggle_loop(self):
        from extensions.video.viewer_commands import toggle_loop
        vw = MagicMock()
        ctx = _make_ctx(vw)
        toggle_loop(ctx)
        vw.toggle_loop.assert_called_once()


class TestTogglePauseInBackground:
    def test_calls_toggle_pause_in_background(self):
        from extensions.video.viewer_commands import toggle_pause_in_background
        vw = MagicMock()
        ctx = _make_ctx(vw)
        toggle_pause_in_background(ctx)
        vw.toggle_pause_in_background.assert_called_once()

    def test_noop_without_instance(self):
        from extensions.video.viewer_commands import toggle_pause_in_background
        ctx = _make_ctx(None)
        result = toggle_pause_in_background(ctx)
        assert result is None


class TestVideoViewerCommandsMeta:
    def test_name(self):
        from extensions.video.viewer_commands import VideoViewerCommands
        assert VideoViewerCommands.NAME == "Video"

    def test_priority_in_extension_range(self):
        from extensions.video.viewer_commands import VideoViewerCommands
        assert VideoViewerCommands.PRIORITY >= 1000

    def test_commands_returns_list(self):
        from extensions.video.viewer_commands import VideoViewerCommands
        cmds = VideoViewerCommands.commands()
        assert isinstance(cmds, list)
        assert len(cmds) > 0

    def test_all_command_paths_start_with_vview(self):
        from extensions.video.viewer_commands import VideoViewerCommands
        cmds = VideoViewerCommands.commands()
        for item in cmds:
            if hasattr(item, 'path'):
                assert item.path.startswith('vview.'), f'{item.path} should start with vview.'

    def test_checkable_commands(self):
        from extensions.video.viewer_commands import VideoViewerCommands
        cmds = VideoViewerCommands.commands()
        checkable_paths = {c.path for c in cmds if hasattr(c, 'checkable') and c.checkable}
        assert 'vview.toggle_mute' in checkable_paths
        assert 'vview.toggle_fit_mode' in checkable_paths
        assert 'vview.toggle_loop' in checkable_paths
