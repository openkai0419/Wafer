import time
from unittest.mock import MagicMock
from PySide6 import QtCore, QtGui, QtWidgets


def _wait_for_widget(widget, attr, expected, timeout=3.0, negate=False):
    app = QtWidgets.QApplication.instance()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        val = getattr(widget, attr)
        if negate and val != expected:
            return
        if not negate and val == expected:
            return
        app.processEvents(QtCore.QEventLoop.AllEvents, 50)
        time.sleep(0.01)


def _wait_for_decode(plugin):
    assert plugin._dispatcher._pool.pool.waitForDone(3000)
    QtWidgets.QApplication.instance().processEvents(QtCore.QEventLoop.AllEvents, 50)


def test_render_posts_decode_without_thumbnail(qtbot, tmp_path):
    from extensions.animated.grid import AnimatedGridPlugin
    from extensions.animated._common import _grid_cache
    from extensions.animated.widget import AnimatedCellWidget
    from PIL import Image

    gif_path = str(tmp_path / "anim.gif")
    frames = [Image.new("RGB", (10, 10), c) for c in ["red", "blue"]]
    frames[0].save(gif_path, save_all=True, append_images=frames[1:], duration=100, loop=0)
    plugin = AnimatedGridPlugin()
    widget = AnimatedCellWidget()
    plugin.render(widget, gif_path, QtCore.QSize(10, 10))
    assert widget._path == gif_path
    _wait_for_widget(widget, "_frames", [], negate=True)
    assert len(widget._frames) >= 2
    _grid_cache.remove(gif_path)
    widget.suspend()
    widget.deleteLater()


def test_render_with_cache_hit(qtbot, tmp_path):
    from extensions.animated.grid import AnimatedGridPlugin
    from extensions.animated._common import _grid_cache
    from extensions.animated.widget import AnimatedCellWidget

    frames = [QtGui.QPixmap(10, 10), QtGui.QPixmap(10, 10)]
    delays = [100, 100]
    path = "/cached/anim.gif"
    _grid_cache.put(path, frames, delays)
    plugin = AnimatedGridPlugin()
    widget = AnimatedCellWidget()
    plugin.render(widget, path, QtCore.QSize(10, 10))
    assert widget._frames is frames
    _grid_cache.remove(path)
    widget.suspend()
    widget.deleteLater()


def test_render_stale_after_suspend_does_not_set_frames(qtbot, tmp_path):
    from extensions.animated.grid import AnimatedGridPlugin
    from extensions.animated._common import _grid_cache
    from extensions.animated.widget import AnimatedCellWidget
    from PIL import Image

    gif_path = str(tmp_path / "anim.gif")
    frames = [Image.new("RGB", (10, 10), c) for c in ["red", "blue"]]
    frames[0].save(gif_path, save_all=True, append_images=frames[1:], duration=100, loop=0)
    plugin = AnimatedGridPlugin()
    widget = AnimatedCellWidget()
    plugin.render(widget, gif_path, QtCore.QSize(10, 10))
    widget.suspend()
    _wait_for_decode(plugin)
    assert widget._frames == []
    _grid_cache.remove(gif_path)
    widget.deleteLater()


def test_render_nonexistent_no_frames(qtbot):
    from extensions.animated.grid import AnimatedGridPlugin
    from extensions.animated.widget import AnimatedCellWidget

    plugin = AnimatedGridPlugin()
    widget = AnimatedCellWidget()
    plugin.render(widget, "/nonexistent/file.gif", QtCore.QSize(10, 10))
    _wait_for_decode(plugin)
    assert widget._path == "/nonexistent/file.gif"
    assert widget._frames == []
    widget.deleteLater()


def test_release_cancels_cancel_slot():
    from extensions.animated.grid import AnimatedGridPlugin
    from wafer.qt.common.dispatcher import CancelSlot

    plugin = AnimatedGridPlugin()
    widget = MagicMock()
    slot = CancelSlot()
    token = slot.renew()
    widget._cancel_slot = slot
    plugin.release(widget)
    assert token.is_cancelled()


def test_render_cancels_previous_token(qtbot, tmp_path):
    from extensions.animated.grid import AnimatedGridPlugin
    from extensions.animated._common import _grid_cache
    from extensions.animated.widget import AnimatedCellWidget
    from PIL import Image

    gif_path = str(tmp_path / "anim.gif")
    frames = [Image.new("RGB", (10, 10), c) for c in ["red", "blue"]]
    frames[0].save(gif_path, save_all=True, append_images=frames[1:], duration=100, loop=0)
    plugin = AnimatedGridPlugin()
    widget = AnimatedCellWidget()
    plugin.render(widget, gif_path, QtCore.QSize(10, 10))
    first_token = widget._cancel_slot._token
    assert first_token is not None
    gif_path2 = str(tmp_path / "anim2.gif")
    frames[0].save(gif_path2, save_all=True, append_images=frames[1:], duration=100, loop=0)
    plugin.render(widget, gif_path2, QtCore.QSize(10, 10))
    assert first_token.is_cancelled()
    assert widget._cancel_slot._token is not first_token
    _grid_cache.remove(gif_path)
    _grid_cache.remove(gif_path2)
    widget.suspend()
    widget.deleteLater()
