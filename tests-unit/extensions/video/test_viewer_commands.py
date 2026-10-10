from unittest.mock import MagicMock


def _make_ctx(vw=None):
    ctx = MagicMock()
    ctx.get_instance = MagicMock(return_value=vw)
    return ctx


class TestSeekBackward:
    def test_calls_seek_negative(self):
        from extensions.video.viewer_commands import seek_backward

        vw = MagicMock()
        ctx = _make_ctx(vw)
        seek_backward(ctx, seconds=10)
        vw.seek.assert_called_once_with(-10)


class TestVolumeUp:
    def test_calls_set_volume_with_increase(self):
        from extensions.video.viewer_commands import volume_up

        vw = MagicMock()
        vw._volume = 50
        ctx = _make_ctx(vw)
        volume_up(ctx, step=5)
        vw.set_volume.assert_called_once_with(55)


class TestVolumeDown:
    def test_calls_set_volume_with_decrease(self):
        from extensions.video.viewer_commands import volume_down

        vw = MagicMock()
        vw._volume = 50
        ctx = _make_ctx(vw)
        volume_down(ctx, step=5)
        vw.set_volume.assert_called_once_with(45)


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
