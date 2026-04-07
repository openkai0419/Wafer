import pytest
from extensions.animated.viewer import AnimatedViewerPlugin
from wafer.plugin.viewer.base import WidgetViewerPlugin


class TestAnimatedViewerPluginAttributes:
    def test_is_widget_viewer_plugin(self):
        assert issubclass(AnimatedViewerPlugin, WidgetViewerPlugin)

    def test_name(self):
        assert AnimatedViewerPlugin.NAME == "animated"

    def test_extensions(self):
        for ext in (".gif", ".apng", ".webp"):
            assert ext in AnimatedViewerPlugin.EXTENSIONS

    def test_priority(self):
        assert AnimatedViewerPlugin.PRIORITY == 200

    def test_priority_above_image(self):
        assert AnimatedViewerPlugin.PRIORITY > 100

    def test_widget_class(self):
        from extensions.animated.viewer_widget import AnimatedViewerWidget

        assert AnimatedViewerPlugin.WIDGET_CLASS is AnimatedViewerWidget


class TestAnimatedViewerPluginCanHandle:
    def test_animated_gif(self, tmp_path):
        from PIL import Image

        gif_path = str(tmp_path / "anim.gif")
        frames = [Image.new("RGB", (10, 10), c) for c in ["red", "blue"]]
        frames[0].save(gif_path, save_all=True, append_images=frames[1:], duration=100, loop=0)
        assert AnimatedViewerPlugin.can_handle(gif_path) is True

    def test_static_gif(self, tmp_path):
        from PIL import Image

        gif_path = str(tmp_path / "static.gif")
        Image.new("RGB", (10, 10), "red").save(gif_path)
        assert AnimatedViewerPlugin.can_handle(gif_path) is False

    def test_match(self):
        assert AnimatedViewerPlugin.match("test.gif")
        assert AnimatedViewerPlugin.match("test.apng")
        assert AnimatedViewerPlugin.match("test.webp")
        assert not AnimatedViewerPlugin.match("test.png")
        assert not AnimatedViewerPlugin.match("test.jpg")


class TestAnimatedViewerPluginDelegation:
    def test_render_calls_load(self):
        from unittest.mock import MagicMock

        plugin = AnimatedViewerPlugin()
        plugin.widget = MagicMock()
        plugin.render("/test.gif")
        plugin.widget.load.assert_called_once_with("/test.gif")

    def test_clear_calls_clear(self):
        from unittest.mock import MagicMock

        plugin = AnimatedViewerPlugin()
        plugin.widget = MagicMock()
        plugin.clear()
        plugin.widget.clear.assert_called_once()

    def test_activate_calls_activate(self):
        from unittest.mock import MagicMock

        plugin = AnimatedViewerPlugin()
        plugin.widget = MagicMock()
        plugin.activate()
        plugin.widget.activate.assert_called_once()

    def test_deactivate_calls_deactivate(self):
        from unittest.mock import MagicMock

        plugin = AnimatedViewerPlugin()
        plugin.widget = MagicMock()
        plugin.deactivate()
        plugin.widget.deactivate.assert_called_once()


class TestAnimatedViewerPluginState:
    def test_save_state(self):
        from unittest.mock import MagicMock

        plugin = AnimatedViewerPlugin()
        plugin.widget = MagicMock()
        plugin.widget._cover_mode = True
        state = plugin.save_state()
        assert state == {"fit_mode": True}

    def test_restore_state(self):
        from unittest.mock import MagicMock

        plugin = AnimatedViewerPlugin()
        plugin.widget = MagicMock()
        plugin.restore_state({"fit_mode": True})
        plugin.widget.set_cover_mode.assert_called_once_with(True)

    def test_restore_state_default(self):
        from unittest.mock import MagicMock

        plugin = AnimatedViewerPlugin()
        plugin.widget = MagicMock()
        plugin.restore_state({})
        plugin.widget.set_cover_mode.assert_called_once_with(False)
