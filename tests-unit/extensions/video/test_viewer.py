import pytest
from extensions.video.viewer import VideoViewerPlugin
from wafer.plugin.viewer.base import WidgetViewerPlugin


class TestVideoViewerPluginAttributes:
    def test_is_widget_viewer_plugin(self):
        assert issubclass(VideoViewerPlugin, WidgetViewerPlugin)

    def test_name(self):
        assert VideoViewerPlugin.NAME == "video"

    def test_extensions_include_common_formats(self):
        for ext in (".mp4", ".mkv", ".webm", ".avi", ".mov"):
            assert ext in VideoViewerPlugin.EXTENSIONS

    def test_widget_class_set(self):
        from extensions.video.viewer_widget import VideoViewerWidget

        assert VideoViewerPlugin.WIDGET_CLASS is VideoViewerWidget

    def test_priority(self):
        assert VideoViewerPlugin.PRIORITY == 100


class TestVideoViewerPluginRender:
    def test_render_calls_load(self):
        from unittest.mock import MagicMock

        plugin = VideoViewerPlugin()
        plugin.widget = MagicMock()
        plugin.render("/test.mp4")
        plugin.widget.load.assert_called_once_with("/test.mp4")

    def test_clear_calls_clear(self):
        from unittest.mock import MagicMock

        plugin = VideoViewerPlugin()
        plugin.widget = MagicMock()
        plugin.clear()
        plugin.widget.clear.assert_called_once()

    def test_activate_calls_activate(self):
        from unittest.mock import MagicMock

        plugin = VideoViewerPlugin()
        plugin.widget = MagicMock()
        plugin.activate()
        plugin.widget.activate.assert_called_once()

    def test_deactivate_calls_deactivate(self):
        from unittest.mock import MagicMock

        plugin = VideoViewerPlugin()
        plugin.widget = MagicMock()
        plugin.deactivate()
        plugin.widget.deactivate.assert_called_once()


class TestVideoViewerPluginState:
    def test_save_state(self):
        from unittest.mock import MagicMock

        plugin = VideoViewerPlugin()
        plugin.widget = MagicMock()
        plugin.widget._volume = 75
        plugin.widget._muted = True
        plugin.widget._speed = 1.5
        plugin.widget._cover_mode = True
        plugin.widget._looping = False
        plugin.widget._pause_in_background = False
        state = plugin.save_state()
        assert state == {
            "volume": 75,
            "muted": True,
            "speed": 1.5,
            "fit_mode": True,
            "loop": False,
            "pause_in_background": False,
        }

    def test_restore_state_calls_setters(self):
        from unittest.mock import MagicMock

        plugin = VideoViewerPlugin()
        plugin.widget = MagicMock()
        state = {
            "volume": 60,
            "muted": True,
            "speed": 2.0,
            "fit_mode": True,
            "loop": True,
            "pause_in_background": False,
        }
        plugin.restore_state(state)
        plugin.widget.set_volume.assert_called_once_with(60)
        plugin.widget.set_muted.assert_called_once_with(True)
        plugin.widget.set_speed.assert_called_once_with(2.0)
        plugin.widget.set_cover_mode.assert_called_once_with(True)
        plugin.widget.set_looping.assert_called_once_with(True)
        plugin.widget.set_pause_in_background.assert_called_once_with(False)

    def test_restore_state_defaults(self):
        from unittest.mock import MagicMock
        from extensions.video.viewer_widget import DEFAULT_VOLUME

        plugin = VideoViewerPlugin()
        plugin.widget = MagicMock()
        plugin.restore_state({})
        plugin.widget.set_volume.assert_called_once_with(DEFAULT_VOLUME)
        plugin.widget.set_muted.assert_called_once_with(False)
        plugin.widget.set_speed.assert_called_once_with(1.0)
        plugin.widget.set_cover_mode.assert_called_once_with(False)
        plugin.widget.set_looping.assert_called_once_with(False)
        plugin.widget.set_pause_in_background.assert_called_once_with(False)

    def test_restore_state_idempotent(self):
        from unittest.mock import MagicMock

        plugin = VideoViewerPlugin()
        plugin.widget = MagicMock()
        state = {"volume": 50, "muted": False, "speed": 1.0, "fit_mode": False, "loop": False, "pause_in_background": False}
        plugin.restore_state(state)
        plugin.restore_state(state)
        assert plugin.widget.set_muted.call_count == 2
        assert plugin.widget.set_cover_mode.call_count == 2
        assert plugin.widget.set_looping.call_count == 2
        assert plugin.widget.set_pause_in_background.call_count == 2


class TestVideoViewerPluginAutoplay:
    def test_set_autoplay_with_callback_returns_true(self):
        from unittest.mock import MagicMock

        plugin = VideoViewerPlugin()
        plugin.widget = MagicMock()
        result = plugin.set_autoplay(lambda: None)
        assert result is True
        plugin.widget.set_autoplay_advance.assert_called_once()

    def test_set_autoplay_none_returns_false(self):
        from unittest.mock import MagicMock

        plugin = VideoViewerPlugin()
        plugin.widget = MagicMock()
        result = plugin.set_autoplay(None)
        assert result is False
        plugin.widget.set_autoplay_advance.assert_called_once_with(None)

    def test_set_autoplay_passes_advance_to_widget(self):
        from unittest.mock import MagicMock

        plugin = VideoViewerPlugin()
        plugin.widget = MagicMock()
        cb = lambda: None
        plugin.set_autoplay(cb)
        plugin.widget.set_autoplay_advance.assert_called_once_with(cb)
