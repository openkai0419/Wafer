import pytest
from extensions.video.viewer import VideoViewerPlugin
from wafer.plugin.viewer.base import WidgetViewerPlugin


class TestVideoViewerPluginAttributes:
    def test_is_widget_viewer_plugin(self):
        assert issubclass(VideoViewerPlugin, WidgetViewerPlugin)

    def test_name(self):
        assert VideoViewerPlugin.NAME == 'video'

    def test_extensions_include_common_formats(self):
        for ext in ('.mp4', '.mkv', '.webm', '.avi', '.mov'):
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
        widget = MagicMock()
        plugin.render(widget, '/test.mp4')
        widget.load.assert_called_once_with('/test.mp4')

    def test_clear_calls_clear(self):
        from unittest.mock import MagicMock
        plugin = VideoViewerPlugin()
        widget = MagicMock()
        plugin.clear(widget)
        widget.clear.assert_called_once()


class TestVideoViewerPluginState:
    def test_save_state(self):
        from unittest.mock import MagicMock
        plugin = VideoViewerPlugin()
        widget = MagicMock()
        widget._volume = 75
        widget._muted = True
        widget._speed = 1.5
        widget._cover_mode = True
        widget._looping = False
        widget._pause_in_background = False
        state = plugin.save_state(widget)
        assert state == {
            'volume': 75,
            'muted': True,
            'speed': 1.5,
            'fit_mode': True,
            'loop': False,
            'pause_in_background': False,
        }

    def test_restore_state_calls_setters(self):
        from unittest.mock import MagicMock, call
        plugin = VideoViewerPlugin()
        widget = MagicMock()
        state = {
            'volume': 60,
            'muted': True,
            'speed': 2.0,
            'fit_mode': True,
            'loop': True,
            'pause_in_background': False,
        }
        plugin.restore_state(widget, state)
        widget.set_volume.assert_called_once_with(60)
        widget.set_muted.assert_called_once_with(True)
        widget.set_speed.assert_called_once_with(2.0)
        widget.set_cover_mode.assert_called_once_with(True)
        widget.set_looping.assert_called_once_with(True)
        widget.set_pause_in_background.assert_called_once_with(False)

    def test_restore_state_defaults(self):
        from unittest.mock import MagicMock
        from extensions.video.viewer_widget import DEFAULT_VOLUME
        plugin = VideoViewerPlugin()
        widget = MagicMock()
        plugin.restore_state(widget, {})
        widget.set_volume.assert_called_once_with(DEFAULT_VOLUME)
        widget.set_muted.assert_called_once_with(False)
        widget.set_speed.assert_called_once_with(1.0)
        widget.set_cover_mode.assert_called_once_with(False)
        widget.set_looping.assert_called_once_with(False)
        widget.set_pause_in_background.assert_called_once_with(False)

    def test_restore_state_idempotent(self):
        from unittest.mock import MagicMock
        plugin = VideoViewerPlugin()
        widget = MagicMock()
        state = {'volume': 50, 'muted': False, 'speed': 1.0, 'fit_mode': False, 'loop': False, 'pause_in_background': False}
        plugin.restore_state(widget, state)
        plugin.restore_state(widget, state)
        assert widget.set_muted.call_count == 2
        assert widget.set_cover_mode.call_count == 2
        assert widget.set_looping.call_count == 2
        assert widget.set_pause_in_background.call_count == 2
