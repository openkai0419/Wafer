import os
import time
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from PySide6 import QtCore, QtGui, QtWidgets


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
        import struct
        from extensions.animated.grid import AnimatedGridPlugin
        png_path = str(tmp_path / 'anim.png')
        sig = b'\x89PNG\r\n\x1a\n'
        ihdr = struct.pack('>I', 13) + b'IHDR' + b'\x00' * 13 + b'\x00' * 4
        actl = struct.pack('>I', 8) + b'acTL' + b'\x00' * 8 + b'\x00' * 4
        with open(png_path, 'wb') as f:
            f.write(sig + ihdr + actl)
        assert AnimatedGridPlugin.can_handle(png_path) is True

    def test_png_with_actl_in_data_not_chunk(self, tmp_path):
        import struct
        from extensions.animated.grid import AnimatedGridPlugin
        png_path = str(tmp_path / 'fake_anim.png')
        sig = b'\x89PNG\r\n\x1a\n'
        data_with_actl = b'\x00' * 4 + b'acTL' + b'\x00' * 5
        ihdr = struct.pack('>I', len(data_with_actl)) + b'IHDR' + data_with_actl + b'\x00' * 4
        idat = struct.pack('>I', 0) + b'IDAT' + b'\x00' * 4
        with open(png_path, 'wb') as f:
            f.write(sig + ihdr + idat)
        assert AnimatedGridPlugin.can_handle(png_path) is False

    def test_animated_webp(self, tmp_path):
        import struct
        from extensions.animated.grid import AnimatedGridPlugin
        webp_path = str(tmp_path / 'anim.webp')
        riff_header = b'RIFF' + b'\x00' * 4 + b'WEBP'
        vp8x = b'VP8X' + struct.pack('<I', 10) + b'\x00' * 10
        anim = b'ANIM' + struct.pack('<I', 6) + b'\x00' * 6
        with open(webp_path, 'wb') as f:
            f.write(riff_header + vp8x + anim)
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


def _wait_for_widget(widget, attr, expected, timeout=3.0):
    app = QtWidgets.QApplication.instance()
    deadline = time.monotonic() + timeout
    while getattr(widget, attr) != expected and time.monotonic() < deadline:
        app.processEvents(QtCore.QEventLoop.AllEvents, 50)
        time.sleep(0.01)


def test_render_posts_decode_without_thumbnail(qtbot, tmp_path):
    from extensions.animated.grid import AnimatedGridPlugin
    from extensions.animated.widget import AnimatedCellWidget, _frame_cache
    from wafer.core.qt.dispatcher import Dispatcher, CancelToken
    from wafer.plugin.grid.cell_job import CellJob
    from PIL import Image
    gif_path = str(tmp_path / 'anim.gif')
    frames = [Image.new('RGB', (10, 10), c) for c in ['red', 'blue']]
    frames[0].save(gif_path, save_all=True, append_images=frames[1:], duration=100, loop=0)
    plugin = AnimatedGridPlugin()
    widget = AnimatedCellWidget()
    dispatcher = Dispatcher()
    render_dispatcher = Dispatcher()
    cache = {}
    job = CellJob(
        index=0, path=gif_path, size=QtCore.QSize(10, 10),
        image_cache=cache, cancel=CancelToken(), dispatcher=dispatcher,
        widget_lookup=lambda i: widget,
        render_dispatcher=render_dispatcher,
    )
    plugin.render(job)
    assert gif_path not in cache
    _wait_for_widget(widget, '_path', gif_path)
    assert len(widget._frames) >= 2
    _frame_cache.remove(gif_path)
    widget.suspend()
    widget.deleteLater()


def test_render_calls_load(qtbot, tmp_path):
    from extensions.animated.grid import AnimatedGridPlugin
    from extensions.animated.widget import AnimatedCellWidget, _frame_cache
    from wafer.core.qt.dispatcher import Dispatcher, CancelToken
    from wafer.plugin.grid.cell_job import CellJob
    from PIL import Image
    gif_path = str(tmp_path / 'anim.gif')
    frames = [Image.new('RGB', (10, 10), c) for c in ['red', 'blue']]
    frames[0].save(gif_path, save_all=True, append_images=frames[1:], duration=100, loop=0)
    plugin = AnimatedGridPlugin()
    widget = AnimatedCellWidget()
    dispatcher = Dispatcher()
    render_dispatcher = Dispatcher()
    job = CellJob(
        index=0, path=gif_path, size=QtCore.QSize(10, 10),
        image_cache={}, cancel=CancelToken(), dispatcher=dispatcher,
        widget_lookup=lambda i: widget,
        render_dispatcher=render_dispatcher,
    )
    plugin.render(job)
    _wait_for_widget(widget, '_path', gif_path)
    assert widget._path == gif_path
    assert len(widget._frames) >= 2
    _frame_cache.remove(gif_path)
    widget.suspend()
    widget.deleteLater()


def test_render_with_cache_hit(qtbot, tmp_path):
    from extensions.animated.grid import AnimatedGridPlugin
    from extensions.animated.widget import AnimatedCellWidget, _frame_cache
    from wafer.core.qt.dispatcher import Dispatcher, CancelToken
    from wafer.plugin.grid.cell_job import CellJob
    frames = [QtGui.QPixmap(10, 10), QtGui.QPixmap(10, 10)]
    delays = [100, 100]
    path = '/cached/anim.gif'
    _frame_cache.put(path, frames, delays)
    plugin = AnimatedGridPlugin()
    widget = AnimatedCellWidget()
    dispatcher = Dispatcher()
    job = CellJob(
        index=0, path=path, size=QtCore.QSize(10, 10),
        image_cache={}, cancel=CancelToken(), dispatcher=dispatcher,
        widget_lookup=lambda i: widget,
    )
    plugin.render(job)
    _wait_for_widget(widget, '_path', path)
    assert widget._frames is frames
    _frame_cache.remove(path)
    widget.suspend()
    widget.deleteLater()


def test_render_cancelled_does_not_invoke(qtbot, tmp_path):
    from extensions.animated.grid import AnimatedGridPlugin
    from extensions.animated.widget import AnimatedCellWidget, _frame_cache
    from wafer.core.qt.dispatcher import Dispatcher, CancelToken
    from wafer.plugin.grid.cell_job import CellJob
    from PIL import Image
    gif_path = str(tmp_path / 'anim.gif')
    frames = [Image.new('RGB', (10, 10), c) for c in ['red', 'blue']]
    frames[0].save(gif_path, save_all=True, append_images=frames[1:], duration=100, loop=0)
    plugin = AnimatedGridPlugin()
    widget = AnimatedCellWidget()
    dispatcher = Dispatcher()
    render_dispatcher = Dispatcher()
    cancel = CancelToken()
    cancel.set()
    job = CellJob(
        index=0, path=gif_path, size=QtCore.QSize(10, 10),
        image_cache={}, cancel=cancel, dispatcher=dispatcher,
        widget_lookup=lambda i: widget,
        render_dispatcher=render_dispatcher,
    )
    plugin.render(job)
    time.sleep(0.1)
    QtWidgets.QApplication.instance().processEvents(QtCore.QEventLoop.AllEvents, 50)
    assert widget._path == ''
    assert widget._frames == []
    widget.deleteLater()


def test_render_nonexistent_no_frames(qtbot):
    from extensions.animated.grid import AnimatedGridPlugin
    from extensions.animated.widget import AnimatedCellWidget
    from wafer.core.qt.dispatcher import Dispatcher, CancelToken
    from wafer.plugin.grid.cell_job import CellJob
    plugin = AnimatedGridPlugin()
    widget = AnimatedCellWidget()
    dispatcher = Dispatcher()
    render_dispatcher = Dispatcher()
    job = CellJob(
        index=0, path='/nonexistent/file.gif', size=QtCore.QSize(10, 10),
        image_cache={}, cancel=CancelToken(), dispatcher=dispatcher,
        widget_lookup=lambda i: widget,
        render_dispatcher=render_dispatcher,
    )
    plugin.render(job)
    time.sleep(0.3)
    QtWidgets.QApplication.instance().processEvents(QtCore.QEventLoop.AllEvents, 50)
    assert widget._path == ''
    assert widget._frames == []
    widget.deleteLater()


class TestDecodeFrames:

    def test_decodes_animated_gif(self, tmp_path):
        from extensions.animated.grid import _decode_frames
        from PIL import Image
        gif_path = str(tmp_path / 'test.gif')
        imgs = [Image.new('RGB', (10, 10), c) for c in ['red', 'blue']]
        imgs[0].save(gif_path, save_all=True, append_images=imgs[1:], duration=100, loop=0)
        job = MagicMock()
        job.is_cancelled.return_value = False
        pixmaps, delays = _decode_frames(gif_path, None, job)
        assert len(pixmaps) == 2
        assert len(delays) == 2

    def test_cancel_mid_decode(self, tmp_path):
        from extensions.animated.grid import _decode_frames
        from PIL import Image
        gif_path = str(tmp_path / 'many.gif')
        imgs = [Image.new('RGB', (10, 10), 'red') for _ in range(20)]
        imgs[0].save(gif_path, save_all=True, append_images=imgs[1:], duration=50, loop=0)
        job = MagicMock()
        job.is_cancelled.return_value = True
        pixmaps, delays = _decode_frames(gif_path, None, job)
        assert pixmaps == [] and delays == []
        job.is_cancelled.assert_called_once()

    def test_scaled_size(self, tmp_path):
        from extensions.animated.grid import _decode_frames
        from PIL import Image
        gif_path = str(tmp_path / 'big.gif')
        imgs = [Image.new('RGB', (100, 100), c) for c in ['red', 'blue']]
        imgs[0].save(gif_path, save_all=True, append_images=imgs[1:], duration=100, loop=0)
        job = MagicMock()
        job.is_cancelled.return_value = False
        pixmaps, delays = _decode_frames(gif_path, QtCore.QSize(50, 50), job)
        assert len(pixmaps) == 2
        for px in pixmaps:
            assert px.width() <= 50 and px.height() <= 50

    def test_nonexistent_file(self):
        from extensions.animated.grid import _decode_frames
        job = MagicMock()
        job.is_cancelled.return_value = False
        pixmaps, delays = _decode_frames('/nonexistent/file.gif', None, job)
        assert pixmaps == []
        assert delays == []


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
