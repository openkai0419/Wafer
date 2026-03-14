import time
import struct

import pytest
from PIL import Image
from PySide6 import QtCore, QtGui, QtWidgets
from unittest.mock import MagicMock

from wafer.app.viewer.grid.grid_view import GridView
from wafer.app.viewer.grid.items import GridItemModel
from wafer.plugin.grid.handler import grid_resolver
from wafer.plugin.grid.base import ImageGridPlugin, WidgetGridPlugin


@pytest.fixture(autouse=True, scope="module")
def _disable_mpv():
    try:
        from extensions.video.widget import MpvGLOverlay
        orig = MpvGLOverlay._mpv, MpvGLOverlay._proc_addr_cb, MpvGLOverlay._init_attempted
        MpvGLOverlay._init_attempted = True
        MpvGLOverlay._mpv = None
        MpvGLOverlay._proc_addr_cb = None
        yield
        MpvGLOverlay._mpv, MpvGLOverlay._proc_addr_cb, MpvGLOverlay._init_attempted = orig
    except ImportError:
        yield


@pytest.fixture(autouse=True, scope="module")
def _configure_command_store(tmp_path_factory):
    from wafer.core.actions.command.state import CommandOptionStore
    prev = CommandOptionStore._instance, CommandOptionStore._initialized, CommandOptionStore._default_path
    CommandOptionStore._instance = None
    CommandOptionStore._initialized = False
    CommandOptionStore._default_path = None
    CommandOptionStore.configure(tmp_path_factory.mktemp("realfile") / "cmd.json")
    yield
    CommandOptionStore._instance, CommandOptionStore._initialized, CommandOptionStore._default_path = prev


def _create_png(path, w=200, h=150):
    Image.new('RGB', (w, h), color=(255, 0, 0)).save(str(path))


def _create_animated_gif(path, w=80, h=60, frames=3):
    imgs = []
    for i in range(frames):
        color = ((i * 80) % 256, 100, 50)
        imgs.append(Image.new('RGB', (w, h), color=color))
    imgs[0].save(
        str(path), save_all=True, append_images=imgs[1:],
        loop=0, duration=100,
    )


def _process_events_until(predicate, timeout_ms=10000):
    app = QtWidgets.QApplication.instance()
    deadline = time.monotonic() + timeout_ms / 1000.0
    while not predicate() and time.monotonic() < deadline:
        app.processEvents(QtCore.QEventLoop.AllEvents, 50)
        time.sleep(0.01)


@pytest.fixture()
def media_dir(tmp_path):
    d = tmp_path / "media"
    d.mkdir()
    _create_png(d / "photo1.png")
    _create_png(d / "photo2.png", 300, 200)
    _create_png(d / "photo3.jpg", 400, 300)
    _create_animated_gif(d / "anim1.gif")
    _create_animated_gif(d / "anim2.gif", 100, 80, 5)
    return d


@pytest.fixture()
def grid_view(qtbot, media_dir):
    root = MagicMock()
    gv = GridView(root)
    gv.resize(800, 600)
    gv.show()
    qtbot.addWidget(gv)
    QtWidgets.QApplication.instance().processEvents()
    return gv


class TestImageFileRouting:

    def test_png_creates_pixmap_item(self, grid_view, media_dir):
        paths = [str(media_dir / "photo1.png")]
        sources = ["test"] * len(paths)
        aspects = [200 / 150]

        layout_done = {'ready': False}
        grid_view.layout_ready.connect(lambda: layout_done.update({'ready': True}))
        grid_view.set_paths(paths, sources, aspects)
        _process_events_until(lambda: layout_done['ready'])
        _process_events_until(lambda: 0 in grid_view.widgets, timeout_ms=5000)

        assert 0 in grid_view.widgets
        assert 0 not in grid_view._additional_widgets

        item = grid_view.widgets[0]
        _process_events_until(
            lambda: getattr(item, 'current_path', None) == paths[0],
            timeout_ms=5000,
        )
        assert item.current_path == paths[0]

    def test_multiple_png_all_get_pixmap_items(self, grid_view, media_dir):
        paths = [
            str(media_dir / "photo1.png"),
            str(media_dir / "photo2.png"),
            str(media_dir / "photo3.jpg"),
        ]
        sources = ["test"] * len(paths)
        aspects = [200 / 150, 300 / 200, 400 / 300]

        layout_done = {'ready': False}
        grid_view.layout_ready.connect(lambda: layout_done.update({'ready': True}))
        grid_view.set_paths(paths, sources, aspects)
        _process_events_until(lambda: layout_done['ready'])
        _process_events_until(lambda: len(grid_view.widgets) >= 3, timeout_ms=5000)

        for i in range(3):
            assert i in grid_view.widgets
            assert i not in grid_view._additional_widgets


class TestAnimatedFileRouting:

    def test_animated_gif_creates_additional_widget(self, grid_view, media_dir):
        paths = [str(media_dir / "anim1.gif")]
        sources = ["test"]
        aspects = [80 / 60]

        layout_done = {'ready': False}
        grid_view.layout_ready.connect(lambda: layout_done.update({'ready': True}))
        grid_view.set_paths(paths, sources, aspects)
        _process_events_until(lambda: layout_done['ready'])
        _process_events_until(lambda: 0 in grid_view._additional_widgets, timeout_ms=5000)

        assert 0 in grid_view._additional_widgets
        assert 0 not in grid_view.widgets


class TestMixedFileRouting:

    def test_png_and_gif_route_correctly(self, grid_view, media_dir):
        paths = [
            str(media_dir / "photo1.png"),
            str(media_dir / "anim1.gif"),
            str(media_dir / "photo2.png"),
        ]
        sources = ["test"] * 3
        aspects = [200 / 150, 80 / 60, 300 / 200]

        layout_done = {'ready': False}
        grid_view.layout_ready.connect(lambda: layout_done.update({'ready': True}))
        grid_view.set_paths(paths, sources, aspects)
        _process_events_until(lambda: layout_done['ready'])

        _process_events_until(
            lambda: 0 in grid_view.widgets and 1 in grid_view._additional_widgets,
            timeout_ms=5000,
        )

        assert 0 in grid_view.widgets, "PNG should be in widgets (FadePixmapItem)"
        assert 0 not in grid_view._additional_widgets
        assert 1 in grid_view._additional_widgets, "GIF should be in _additional_widgets"
        assert 1 not in grid_view.widgets
        assert 2 in grid_view.widgets, "Second PNG should be in widgets"

    def test_no_set_image_error_on_animated(self, grid_view, media_dir):
        paths = [
            str(media_dir / "anim1.gif"),
            str(media_dir / "anim2.gif"),
            str(media_dir / "photo1.png"),
        ]
        sources = ["test"] * 3
        aspects = [80 / 60, 100 / 80, 200 / 150]

        layout_done = {'ready': False}
        grid_view.layout_ready.connect(lambda: layout_done.update({'ready': True}))
        grid_view.set_paths(paths, sources, aspects)
        _process_events_until(lambda: layout_done['ready'])

        _process_events_until(
            lambda: 2 in grid_view.widgets,
            timeout_ms=5000,
        )

        time.sleep(0.5)
        QtWidgets.QApplication.instance().processEvents()

        assert 0 in grid_view._additional_widgets
        assert 1 in grid_view._additional_widgets
        assert 2 in grid_view.widgets


class TestImageCacheIntegration:

    def test_loaded_image_saved_to_cache(self, grid_view, media_dir):
        path = str(media_dir / "photo1.png")
        paths = [path]
        sources = ["test"]
        aspects = [200 / 150]

        layout_done = {'ready': False}
        grid_view.layout_ready.connect(lambda: layout_done.update({'ready': True}))
        grid_view.set_paths(paths, sources, aspects)
        _process_events_until(lambda: layout_done['ready'])

        _process_events_until(
            lambda: grid_view.image_cache.get(path) is not None,
            timeout_ms=5000,
        )

        cached = grid_view.image_cache.get(path)
        assert cached is not None
        assert not cached.isNull()


class TestSetPathsReplace:

    def test_replace_paths_clears_old_widgets(self, grid_view, media_dir):
        paths1 = [str(media_dir / "photo1.png")]
        grid_view.set_paths(paths1, ["test"], [200 / 150])
        _process_events_until(lambda: 0 in grid_view.widgets, timeout_ms=5000)
        assert 0 in grid_view.widgets

        paths2 = [str(media_dir / "anim1.gif")]
        grid_view.set_paths(paths2, ["test"], [80 / 60])
        _process_events_until(lambda: 0 in grid_view._additional_widgets, timeout_ms=5000)

        assert 0 not in grid_view.widgets
        assert 0 in grid_view._additional_widgets

    def test_replace_animated_with_image(self, grid_view, media_dir):
        grid_view.set_paths(
            [str(media_dir / "anim1.gif")], ["test"], [80 / 60],
        )
        _process_events_until(lambda: 0 in grid_view._additional_widgets, timeout_ms=5000)

        grid_view.set_paths(
            [str(media_dir / "photo1.png")], ["test"], [200 / 150],
        )
        _process_events_until(lambda: 0 in grid_view.widgets, timeout_ms=5000)

        assert 0 in grid_view.widgets
        assert 0 not in grid_view._additional_widgets


class TestPluginResolution:

    def test_resolve_chain_gif_has_animated_first(self, media_dir):
        path = str(media_dir / "anim1.gif")
        chain = grid_resolver.resolve_chain(path)
        assert len(chain) >= 2
        assert issubclass(chain[0], WidgetGridPlugin)

    def test_resolve_chain_png_has_image_first(self, media_dir):
        path = str(media_dir / "photo1.png")
        chain = grid_resolver.resolve_chain(path)
        assert len(chain) >= 1
        found_image = False
        for cls in chain:
            if issubclass(cls, ImageGridPlugin) and not issubclass(cls, WidgetGridPlugin):
                found_image = True
                break
        assert found_image

    def test_resolve_image_instance_for_gif(self, media_dir):
        path = str(media_dir / "anim1.gif")
        inst = grid_resolver.resolve_image_instance(path)
        assert inst is not None
        assert isinstance(inst, ImageGridPlugin)
        assert not isinstance(inst, WidgetGridPlugin)
