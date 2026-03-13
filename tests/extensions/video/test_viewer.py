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
