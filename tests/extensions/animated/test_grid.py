import os
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from PySide6 import QtCore, QtGui


def test_animated_grid_plugin_attributes():
    from extensions.animated.grid import AnimatedGridPlugin
    assert AnimatedGridPlugin.NAME == 'animated'
    assert '.gif' in AnimatedGridPlugin.EXTENSIONS
    assert '.apng' in AnimatedGridPlugin.EXTENSIONS
    assert '.webp' in AnimatedGridPlugin.EXTENSIONS
    assert '.png' in AnimatedGridPlugin.EXTENSIONS
    assert AnimatedGridPlugin.PRIORITY == 200
    assert AnimatedGridPlugin.WIDGET_CLASS is not None
    assert AnimatedGridPlugin.REQUIRE_THUMBNAIL is True


def test_animated_grid_plugin_match():
    from extensions.animated.grid import AnimatedGridPlugin
    assert AnimatedGridPlugin.match('test.gif')
    assert AnimatedGridPlugin.match('test.GIF')
    assert AnimatedGridPlugin.match('test.apng')
    assert AnimatedGridPlugin.match('test.webp')
    assert AnimatedGridPlugin.match('test.png')
    assert not AnimatedGridPlugin.match('test.jpg')
    assert not AnimatedGridPlugin.match('test.mp4')


def test_animated_grid_plugin_is_widget_plugin():
    from extensions.animated.grid import AnimatedGridPlugin
    from wafer.plugin.grid.base import WidgetGridPlugin
    assert issubclass(AnimatedGridPlugin, WidgetGridPlugin)


def test_animated_grid_plugin_priority_above_image():
    from extensions.animated.grid import AnimatedGridPlugin
    assert AnimatedGridPlugin.PRIORITY > 100


class TestCanHandle:

    def test_animated_gif(self, tmp_path):
        from extensions.animated.grid import AnimatedGridPlugin
        from PIL import Image
        gif_path = str(tmp_path / 'anim.gif')
        frames = [Image.new('RGB', (10, 10), c) for c in ['red', 'blue']]
        frames[0].save(gif_path, save_all=True, append_images=frames[1:], duration=100, loop=0)
        assert AnimatedGridPlugin.can_handle(gif_path) is True

    def test_static_gif(self, tmp_path):
        from extensions.animated.grid import AnimatedGridPlugin
        from PIL import Image
        gif_path = str(tmp_path / 'static.gif')
        Image.new('RGB', (10, 10)).save(gif_path)
        assert AnimatedGridPlugin.can_handle(gif_path) is False

    def test_static_png(self, tmp_path):
        from extensions.animated.grid import AnimatedGridPlugin
        from PIL import Image
        png_path = str(tmp_path / 'static.png')
        Image.new('RGB', (10, 10)).save(png_path)
        assert AnimatedGridPlugin.can_handle(png_path) is False

    def test_apng_extension(self, tmp_path):
        from extensions.animated.grid import AnimatedGridPlugin
        apng_path = str(tmp_path / 'anim.apng')
        with open(apng_path, 'wb') as f:
            f.write(b'\x89PNG\r\n\x1a\n')
        assert AnimatedGridPlugin.can_handle(apng_path) is True

    def test_png_with_actl_chunk(self, tmp_path):
        from extensions.animated.grid import AnimatedGridPlugin
        png_path = str(tmp_path / 'anim.png')
        with open(png_path, 'wb') as f:
            f.write(b'\x89PNG\r\n\x1a\n' + b'\x00' * 20 + b'acTL' + b'\x00' * 20)
        assert AnimatedGridPlugin.can_handle(png_path) is True

    def test_animated_webp(self, tmp_path):
        from extensions.animated.grid import AnimatedGridPlugin
        webp_path = str(tmp_path / 'anim.webp')
        with open(webp_path, 'wb') as f:
            f.write(b'RIFF' + b'\x00' * 4 + b'WEBP' + b'VP8X' + b'\x00' * 10 + b'ANIM' + b'\x00' * 10)
        assert AnimatedGridPlugin.can_handle(webp_path) is True

    def test_static_webp(self, tmp_path):
        from extensions.animated.grid import AnimatedGridPlugin
        from PIL import Image
        webp_path = str(tmp_path / 'static.webp')
        Image.new('RGB', (10, 10)).save(webp_path, 'WEBP')
        assert AnimatedGridPlugin.can_handle(webp_path) is False

    def test_nonexistent_file(self):
        from extensions.animated.grid import AnimatedGridPlugin
        assert AnimatedGridPlugin.can_handle('/nonexistent/file.gif') is False

    def test_unknown_extension(self, tmp_path):
        from extensions.animated.grid import AnimatedGridPlugin
        txt_path = str(tmp_path / 'file.txt')
        with open(txt_path, 'w') as f:
            f.write('hello')
        assert AnimatedGridPlugin.can_handle(txt_path) is False


def test_render_calls_load(qtbot, tmp_path):
    from extensions.animated.grid import AnimatedGridPlugin
    from extensions.animated.widget import AnimatedCellWidget
    from PIL import Image
    gif_path = str(tmp_path / 'anim.gif')
    frames = [Image.new('RGB', (10, 10), c) for c in ['red', 'blue']]
    frames[0].save(gif_path, save_all=True, append_images=frames[1:], duration=100, loop=0)
    plugin = AnimatedGridPlugin()
    widget = AnimatedCellWidget()
    plugin.render(widget, gif_path)
    assert widget._path == gif_path
    widget.suspend()
    widget.deleteLater()


def test_render_nonexistent_starts_runner(qtbot, tmp_path):
    from extensions.animated.grid import AnimatedGridPlugin
    from extensions.animated.widget import AnimatedCellWidget
    plugin = AnimatedGridPlugin()
    widget = AnimatedCellWidget()
    plugin.render(widget, '/nonexistent/file.gif')
    assert widget._path == '/nonexistent/file.gif'
    widget.suspend()
    widget.deleteLater()


def test_release_calls_suspend():
    from extensions.animated.grid import AnimatedGridPlugin
    plugin = AnimatedGridPlugin()
    widget = MagicMock()
    plugin.release(widget)
    widget.suspend.assert_called_once()


def test_appear_calls_on_appeared():
    from extensions.animated.grid import AnimatedGridPlugin
    plugin = AnimatedGridPlugin()
    widget = MagicMock()
    plugin.appear(widget)
    widget.on_appeared.assert_called_once()


def test_disappear_calls_on_disappeared():
    from extensions.animated.grid import AnimatedGridPlugin
    plugin = AnimatedGridPlugin()
    widget = MagicMock()
    plugin.disappear(widget)
    widget.on_disappeared.assert_called_once()


def test_select_calls_on_selected():
    from extensions.animated.grid import AnimatedGridPlugin
    plugin = AnimatedGridPlugin()
    widget = MagicMock()
    plugin.select(widget)
    widget.on_selected.assert_called_once()


def test_deselect_calls_on_deselected():
    from extensions.animated.grid import AnimatedGridPlugin
    plugin = AnimatedGridPlugin()
    widget = MagicMock()
    plugin.deselect(widget)
    widget.on_deselected.assert_called_once()


def test_on_thumb_loaded_calls_set_thumbnail():
    from extensions.animated.grid import AnimatedGridPlugin
    plugin = AnimatedGridPlugin()
    widget = MagicMock()
    image = MagicMock()
    plugin.on_thumb_loaded(widget, image)
    widget.set_thumbnail.assert_called_once_with(image)
