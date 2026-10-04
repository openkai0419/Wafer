from extensions.video.viewer import VideoViewerPlugin


def _make_plugin(widget=None):
    plugin = VideoViewerPlugin.__new__(VideoViewerPlugin)
    plugin.widget = widget
    return plugin


class TestVideoViewerPluginState:
    def test_save_ui_state(self):
        from unittest.mock import MagicMock

        plugin = _make_plugin(MagicMock())
        plugin.widget._volume = 75
        plugin.widget.muted = True
        plugin.widget._speed = 1.5
        plugin.widget.cover_mode = True
        plugin.widget.looping = False
        plugin.widget.pause_in_background = False
        state = plugin.save_ui_state()
        assert state == {
            "volume": 75,
            "muted": True,
            "speed": 1.5,
            "fit_mode": True,
            "loop": False,
            "pause_in_background": False,
        }

    def test_restore_ui_state_calls_setters(self):
        from unittest.mock import MagicMock

        plugin = _make_plugin(MagicMock())
        state = {
            "volume": 60,
            "muted": True,
            "speed": 2.0,
            "fit_mode": True,
            "loop": True,
            "pause_in_background": False,
        }
        plugin.restore_ui_state(state)
        plugin.widget.set_volume.assert_called_once_with(60)
        plugin.widget.set_muted.assert_called_once_with(True)
        plugin.widget.set_speed.assert_called_once_with(2.0)
        plugin.widget.set_cover_mode.assert_called_once_with(True)
        plugin.widget.set_looping.assert_called_once_with(True)
        plugin.widget.set_pause_in_background.assert_called_once_with(False)

    def test_restore_ui_state_defaults(self):
        from unittest.mock import MagicMock
        from extensions.video.viewer_widget import DEFAULT_VOLUME

        plugin = _make_plugin(MagicMock())
        plugin.restore_ui_state({})
        plugin.widget.set_volume.assert_called_once_with(DEFAULT_VOLUME)
        plugin.widget.set_muted.assert_called_once_with(False)
        plugin.widget.set_speed.assert_called_once_with(1.0)
        plugin.widget.set_cover_mode.assert_called_once_with(False)
        plugin.widget.set_looping.assert_called_once_with(True)
        plugin.widget.set_pause_in_background.assert_called_once_with(False)


class TestVideoViewerPluginAutoplay:
    def test_set_autoplay_with_callback_returns_true(self):
        from unittest.mock import MagicMock

        plugin = _make_plugin(MagicMock())
        cb = lambda: None
        result = plugin.set_autoplay(cb)
        assert result is True
        plugin.widget.set_autoplay_advance.assert_called_once_with(cb)

    def test_set_autoplay_none_returns_false(self):
        from unittest.mock import MagicMock

        plugin = _make_plugin(MagicMock())
        result = plugin.set_autoplay(None)
        assert result is False
        plugin.widget.set_autoplay_advance.assert_called_once_with(None)
