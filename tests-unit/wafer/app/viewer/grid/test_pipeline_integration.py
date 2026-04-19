import time
import threading

import pytest
from PySide6 import QtCore, QtGui, QtWidgets
from unittest.mock import MagicMock

from wafer.core.qt.dispatcher import Dispatcher, CancelToken
from wafer.app.viewer.grid.pipeline import GridPipeline
from wafer.plugin.grid.base import WidgetGridPlugin
from wafer.plugin.grid.handler import WIDGET, IMAGE

_noop_appear = lambda i: None


@pytest.fixture()
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


@pytest.fixture()
def dispatcher(qapp):
    from wafer.core.qt.thread import SimpleThreadPool

    pool = SimpleThreadPool("test_pipeline_integ")
    d = Dispatcher(pool=pool)
    yield d
    pool.pool.waitForDone(5000)


class _FakeCache:
    def __init__(self):
        self.store = {}

    def get(self, key, default=None):
        return self.store.get(key, default)

    def get_if_sufficient(self, key, size, default=None):
        image = self.store.get(key)
        if image is not None and image.width() >= size.width() and image.height() >= size.height():
            return image
        return default

    def __setitem__(self, key, value):
        self.store[key] = value

    def __contains__(self, key):
        return key in self.store


def _process_events_until(predicate, timeout_ms=5000):
    app = QtWidgets.QApplication.instance()
    deadline = time.monotonic() + timeout_ms / 1000.0
    while not predicate() and time.monotonic() < deadline:
        app.processEvents(QtCore.QEventLoop.AllEvents, 50)
        time.sleep(0.01)


def _make_image(w=100, h=100):
    img = QtGui.QImage(w, h, QtGui.QImage.Format_ARGB32)
    img.fill(0)
    return img


class _StubImagePlugin:
    NAME = "stub_image"
    EXTENSIONS = (".png", ".jpg")
    PRIORITY = 0

    @classmethod
    def can_handle(cls, path):
        return True


class _StubWidgetPlugin(WidgetGridPlugin):
    NAME = "stub_widget"
    EXTENSIONS = (".mp4",)
    WIDGET_CLASS = MagicMock
    REQUIRE_THUMBNAIL = True
    PRIORITY = 5

    def render(self, widget, path, size):
        self._last_widget = widget
        self._last_path = path

    def on_thumb_loaded(self, widget, image):
        widget.set_thumb(image)


class _SlowImagePlugin:
    NAME = "slow_image"
    EXTENSIONS = (".slow",)
    PRIORITY = 0

    @classmethod
    def can_handle(cls, path):
        return True


def _fake_resolver(plugin=None, load_fn=None):
    _cls = type(plugin) if plugin else None
    _inst = plugin
    _load = load_fn if load_fn is not None else (lambda p, s=None: _make_image())
    _kind = WIDGET if isinstance(plugin, WidgetGridPlugin) else IMAGE

    class _Registry:
        def instance(self, name):
            return _inst

    class _Resolver:
        registry = _Registry()

        def resolve_merged_chain(self, path):
            return [(_cls, _kind)] if _cls else []

        def load(self, path, size=None):
            return _load(path, size)

    return _Resolver()


class TestPipelineRenderImageFlow:
    def test_image_render_delivers_to_widget(self, dispatcher):
        widgets = {}
        cache = _FakeCache()
        pipeline = GridPipeline(dispatcher, dispatcher, dispatcher, cache, lambda i: widgets.get(i), lambda i, n: None, _noop_appear)

        widget = MagicMock()
        widgets[0] = widget

        plugin = _StubImagePlugin()

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("wafer.app.viewer.grid.pipeline.grid_resolver", _fake_resolver(plugin))
            pipeline.schedule_render(0, "/photo.png", QtCore.QSize(200, 200))

        _process_events_until(lambda: widget.set_image.called)
        widget.set_image.assert_called_once()
        args = widget.set_image.call_args[0]
        assert isinstance(args[0], QtGui.QImage)
        assert args[1] == "/photo.png"
        assert "/photo.png" in cache

    def test_image_render_uses_sufficient_cache(self, dispatcher):
        widgets = {}
        cache = _FakeCache()
        pipeline = GridPipeline(dispatcher, dispatcher, dispatcher, cache, lambda i: widgets.get(i), lambda i, n: None, _noop_appear)

        widget = MagicMock()
        widgets[0] = widget
        cached_img = _make_image(200, 200)
        cache["/photo.png"] = cached_img

        plugin = _StubImagePlugin()

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("wafer.app.viewer.grid.pipeline.grid_resolver", _fake_resolver(plugin))
            pipeline.schedule_render(0, "/photo.png", QtCore.QSize(200, 200))

        _process_events_until(lambda: widget.set_image.called)
        args = widget.set_image.call_args[0]
        assert args[0] is cached_img

    def test_image_render_reloads_when_cache_undersized(self, dispatcher):
        widgets = {}
        cache = _FakeCache()
        pipeline = GridPipeline(dispatcher, dispatcher, dispatcher, cache, lambda i: widgets.get(i), lambda i, n: None, _noop_appear)

        widget = MagicMock()
        widgets[0] = widget
        small_img = _make_image(50, 50)
        cache["/photo.png"] = small_img

        plugin = _StubImagePlugin()

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("wafer.app.viewer.grid.pipeline.grid_resolver", _fake_resolver(plugin))
            pipeline.schedule_render(0, "/photo.png", QtCore.QSize(200, 200))

        _process_events_until(lambda: widget.set_image.called)
        args = widget.set_image.call_args[0]
        reloaded = args[0]
        assert reloaded is not small_img
        assert reloaded.width() == 200 and reloaded.height() == 200
        assert cache.store["/photo.png"] is reloaded


class TestPipelineCancelDuringRender:
    def test_cancel_before_invoke_skips_widget(self, dispatcher):
        widgets = {}
        cache = _FakeCache()
        pipeline = GridPipeline(dispatcher, dispatcher, dispatcher, cache, lambda i: widgets.get(i), lambda i, n: None, _noop_appear)

        widget = MagicMock()
        widgets[0] = widget

        plugin = _SlowImagePlugin()

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("wafer.app.viewer.grid.pipeline.grid_resolver", _fake_resolver(plugin))
            pipeline.schedule_render(0, "/slow.slow", QtCore.QSize(200, 200))
            time.sleep(0.05)
            pipeline.cancel_index(0)

        time.sleep(0.5)
        QtWidgets.QApplication.instance().processEvents()
        widget.set_image.assert_not_called()

    def test_reschedule_cancels_previous(self, dispatcher):
        widgets = {}
        cache = _FakeCache()
        pipeline = GridPipeline(dispatcher, dispatcher, dispatcher, cache, lambda i: widgets.get(i), lambda i, n: None, _noop_appear)

        widget = MagicMock()
        widgets[0] = widget

        plugin = _StubImagePlugin()

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("wafer.app.viewer.grid.pipeline.grid_resolver", _fake_resolver(plugin))

            pipeline.schedule_render(0, "/first.png", QtCore.QSize(200, 200))
            first_token = pipeline._active.get(0)
            pipeline.schedule_render(0, "/second.png", QtCore.QSize(200, 200))

        assert first_token.is_cancelled()
        _process_events_until(lambda: widget.set_image.called)
        final_path = widget.set_image.call_args[0][1]
        assert final_path == "/second.png"


class TestPipelineWidgetRecycle:
    def test_recycle_prevents_delivery(self, dispatcher):
        widgets = {}
        cache = _FakeCache()
        pipeline = GridPipeline(dispatcher, dispatcher, dispatcher, cache, lambda i: widgets.get(i), lambda i, n: None, _noop_appear)

        widget = MagicMock()
        widgets[0] = widget

        deliver_event = threading.Event()

        class _BlockingPlugin:
            NAME = "blocking"
            EXTENSIONS = (".blk",)

            @classmethod
            def can_handle(cls, path):
                return True

            def load(self, path, size=None):
                deliver_event.wait(timeout=2)
                return _make_image()

        plugin = _BlockingPlugin()

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("wafer.app.viewer.grid.pipeline.grid_resolver", _fake_resolver(plugin))
            pipeline.schedule_render(0, "/block.blk", QtCore.QSize(200, 200))

        del widgets[0]
        pipeline.cancel_index(0)
        deliver_event.set()

        time.sleep(0.3)
        QtWidgets.QApplication.instance().processEvents()
        widget.set_image.assert_not_called()


class TestPipelineWidgetPluginThumbnail:
    def test_widget_plugin_render_then_thumbnail(self, dispatcher):
        widgets = {}
        cache = _FakeCache()
        pipeline = GridPipeline(dispatcher, dispatcher, dispatcher, cache, lambda i: widgets.get(i), lambda i, n: None, _noop_appear)

        widget = MagicMock()
        widgets[0] = widget

        plugin = _StubWidgetPlugin()
        thumb_img = _make_image(64, 64)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("wafer.app.viewer.grid.pipeline.grid_resolver", _fake_resolver(plugin, load_fn=lambda p, s=None: thumb_img))
            pipeline.schedule_render(0, "/vid.mp4", QtCore.QSize(300, 300))
            _process_events_until(lambda: widget.set_thumb.called)

        widget.set_thumb.assert_called_once()
        assert widget.set_thumb.call_args[0][0] is thumb_img
        assert "/vid.mp4" in cache

    def test_widget_plugin_thumbnail_uses_cache(self, dispatcher):
        widgets = {}
        cache = _FakeCache()
        cached_thumb = _make_image(300, 300)
        cache["/vid.mp4"] = cached_thumb
        pipeline = GridPipeline(dispatcher, dispatcher, dispatcher, cache, lambda i: widgets.get(i), lambda i, n: None, _noop_appear)

        widget = MagicMock()
        widgets[0] = widget

        plugin = _StubWidgetPlugin()

        with pytest.MonkeyPatch.context() as mp:
            load_called = {"count": 0}

            def fake_load(p, s=None):
                load_called["count"] += 1
                return _make_image()

            mp.setattr("wafer.app.viewer.grid.pipeline.grid_resolver", _fake_resolver(plugin, load_fn=fake_load))
            pipeline.schedule_render(0, "/vid.mp4", QtCore.QSize(300, 300))
            _process_events_until(lambda: widget.set_thumb.called)

        assert load_called["count"] == 0
        assert widget.set_thumb.call_args[0][0] is cached_thumb


class TestPipelineLayoutToRenderFlow:
    def test_layout_ready_to_schedule_render(self, dispatcher):
        widgets = {}
        cache = _FakeCache()
        pipeline = GridPipeline(dispatcher, dispatcher, dispatcher, cache, lambda i: widgets.get(i), lambda i, n: None, _noop_appear)

        layout_received = {}

        def on_layout(layout):
            layout_received["data"] = layout

        pipeline.layout_ready.connect(on_layout)

        pipeline.request_layout([1.0, 1.5, 0.8], 100, 4, 800, 600)
        _process_events_until(lambda: "data" in layout_received)

        layout = layout_received["data"]
        assert len(layout) == 3

        widget = MagicMock()
        widgets[0] = widget
        plugin = _StubImagePlugin()

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("wafer.app.viewer.grid.pipeline.grid_resolver", _fake_resolver(plugin))
            rect = layout[0]
            pipeline.schedule_render(0, "/img.png", rect.size())

        _process_events_until(lambda: widget.set_image.called)
        widget.set_image.assert_called_once()


class TestPipelineCancelAllDuringRender:
    def test_cancel_all_stops_active_renders(self, dispatcher):
        widgets = {}
        cache = _FakeCache()
        pipeline = GridPipeline(dispatcher, dispatcher, dispatcher, cache, lambda i: widgets.get(i), lambda i, n: None, _noop_appear)

        barrier = threading.Event()

        class _WaitPlugin:
            NAME = "wait"
            EXTENSIONS = (".wait",)

            @classmethod
            def can_handle(cls, path):
                return True

            def load(self, path, size=None):
                barrier.wait(timeout=2)
                return _make_image()

        plugin = _WaitPlugin()
        w0, w1 = MagicMock(), MagicMock()
        widgets[0] = w0
        widgets[1] = w1

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("wafer.app.viewer.grid.pipeline.grid_resolver", _fake_resolver(plugin))
            pipeline.schedule_render(0, "/a.wait", QtCore.QSize(100, 100))
            pipeline.schedule_render(1, "/b.wait", QtCore.QSize(100, 100))

        pipeline.cancel_all()
        barrier.set()
        assert pipeline.active_count() == 0

        time.sleep(0.4)
        QtWidgets.QApplication.instance().processEvents()
        w0.set_image.assert_not_called()
        w1.set_image.assert_not_called()


class TestPipelineFallbackRender:
    def test_fallback_delivers_image_for_unknown_file(self, dispatcher):
        widgets = {}
        cache = _FakeCache()
        pipeline = GridPipeline(dispatcher, dispatcher, dispatcher, cache, lambda i: widgets.get(i), lambda i, n: None, _noop_appear)

        widget = MagicMock()
        widgets[0] = widget
        fallback_img = _make_image(150, 150)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("wafer.app.viewer.grid.pipeline.grid_resolver", _fake_resolver(load_fn=lambda p, s=None: fallback_img))
            pipeline.schedule_render(0, "/song.mp3", QtCore.QSize(200, 200))
            _process_events_until(lambda: widget.set_image.called)

        widget.set_image.assert_called_once()
        args = widget.set_image.call_args[0]
        assert args[0] is fallback_img
        assert args[1] == "/song.mp3"
        assert cache.store["/song.mp3"] is fallback_img

    def test_fallback_shows_error_placeholder_when_load_returns_none(self, dispatcher):
        widgets = {}
        cache = _FakeCache()
        pipeline = GridPipeline(dispatcher, dispatcher, dispatcher, cache, lambda i: widgets.get(i), lambda i, n: None, _noop_appear)

        widget = MagicMock()
        widgets[0] = widget

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("wafer.app.viewer.grid.pipeline.grid_resolver", _fake_resolver(load_fn=lambda p, s=None: None))
            pipeline.schedule_render(0, "/data.bin", QtCore.QSize(200, 200))
            _process_events_until(lambda: widget.set_image.called)

        widget.set_image.assert_called_once()
        img = widget.set_image.call_args[0][0]
        assert isinstance(img, QtGui.QImage)
        assert not img.isNull()
        assert cache.store["/data.bin"] is img

    def test_fallback_uses_sufficient_cache(self, dispatcher):
        widgets = {}
        cache = _FakeCache()
        pipeline = GridPipeline(dispatcher, dispatcher, dispatcher, cache, lambda i: widgets.get(i), lambda i, n: None, _noop_appear)

        widget = MagicMock()
        widgets[0] = widget
        cached_img = _make_image(200, 200)
        cache["/archive.zip"] = cached_img

        load_called = {"count": 0}

        with pytest.MonkeyPatch.context() as mp:

            def fake_load(p, s=None):
                load_called["count"] += 1
                return _make_image()

            mp.setattr("wafer.app.viewer.grid.pipeline.grid_resolver", _fake_resolver(load_fn=fake_load))
            pipeline.schedule_render(0, "/archive.zip", QtCore.QSize(200, 200))

        _process_events_until(lambda: widget.set_image.called)
        assert load_called["count"] == 0
        assert widget.set_image.call_args[0][0] is cached_img

    def test_fallback_reloads_when_cache_undersized(self, dispatcher):
        widgets = {}
        cache = _FakeCache()
        pipeline = GridPipeline(dispatcher, dispatcher, dispatcher, cache, lambda i: widgets.get(i), lambda i, n: None, _noop_appear)

        widget = MagicMock()
        widgets[0] = widget
        small_img = _make_image(50, 50)
        cache["/archive.zip"] = small_img
        reload_img = _make_image(200, 200)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("wafer.app.viewer.grid.pipeline.grid_resolver", _fake_resolver(load_fn=lambda p, s=None: reload_img))
            pipeline.schedule_render(0, "/archive.zip", QtCore.QSize(200, 200))
            _process_events_until(lambda: widget.set_image.called)

        args = widget.set_image.call_args[0]
        assert args[0] is reload_img
        assert cache.store["/archive.zip"] is reload_img

    def test_fallback_cancellable(self, dispatcher):
        widgets = {}
        cache = _FakeCache()
        pipeline = GridPipeline(dispatcher, dispatcher, dispatcher, cache, lambda i: widgets.get(i), lambda i, n: None, _noop_appear)

        widget = MagicMock()
        widgets[0] = widget
        barrier = threading.Event()

        with pytest.MonkeyPatch.context() as mp:

            def slow_load(p, s=None):
                barrier.wait(timeout=2)
                return _make_image()

            mp.setattr("wafer.app.viewer.grid.pipeline.grid_resolver", _fake_resolver(load_fn=slow_load))
            pipeline.schedule_render(0, "/song.mp3", QtCore.QSize(200, 200))
            time.sleep(0.05)
            pipeline.cancel_index(0)
            barrier.set()

        time.sleep(0.3)
        QtWidgets.QApplication.instance().processEvents()
        widget.set_image.assert_not_called()


class TestPipelineFullsizeKeyOptimization:
    def test_fullsize_cache_hit_skips_plugin_load(self, dispatcher):
        from wafer.app.viewer.grid.cachemanager import fullsize_key

        widgets = {}
        cache = _FakeCache()
        pipeline = GridPipeline(dispatcher, dispatcher, dispatcher, cache, lambda i: widgets.get(i), lambda i, n: None, _noop_appear)

        widget = MagicMock()
        widgets[0] = widget
        fullsize_img = _make_image(400, 400)
        cache[fullsize_key("/photo.png")] = fullsize_img

        load_called = {"count": 0}

        class _TrackingPlugin:
            NAME = "tracking"
            EXTENSIONS = (".png",)

            @classmethod
            def can_handle(cls, path):
                return True

            def load(self, path, size=None):
                load_called["count"] += 1
                return _make_image(200, 200)

        plugin = _TrackingPlugin()

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("wafer.app.viewer.grid.pipeline.grid_resolver", _fake_resolver(plugin))
            pipeline.schedule_render(0, "/photo.png", QtCore.QSize(200, 200))

        _process_events_until(lambda: widget.set_image.called)
        assert load_called["count"] == 0
        assert widget.set_image.call_args[0][0] is fullsize_img

    def test_fullsize_cache_not_used_for_widget_plugin(self, dispatcher):
        from wafer.app.viewer.grid.cachemanager import fullsize_key

        widgets = {}
        cache = _FakeCache()
        pipeline = GridPipeline(dispatcher, dispatcher, dispatcher, cache, lambda i: widgets.get(i), lambda i, n: None, _noop_appear)

        widget = MagicMock()
        widgets[0] = widget
        fullsize_img = _make_image(400, 400)
        cache[fullsize_key("/vid.mp4")] = fullsize_img

        plugin = _StubWidgetPlugin()

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("wafer.app.viewer.grid.pipeline.grid_resolver", _fake_resolver(plugin, load_fn=lambda p, s=None: _make_image(64, 64)))
            pipeline.schedule_render(0, "/vid.mp4", QtCore.QSize(300, 300))
            _process_events_until(lambda: widget.set_thumb.called)

        widget.set_thumb.assert_called_once()
        assert widget.set_image.call_count == 0

    def test_fallback_prefers_fullsize_over_normal_cache(self, dispatcher):
        from wafer.app.viewer.grid.cachemanager import fullsize_key

        widgets = {}
        cache = _FakeCache()
        pipeline = GridPipeline(dispatcher, dispatcher, dispatcher, cache, lambda i: widgets.get(i), lambda i, n: None, _noop_appear)

        widget = MagicMock()
        widgets[0] = widget
        normal_img = _make_image(100, 100)
        fullsize_img = _make_image(400, 400)
        cache["/song.mp3"] = normal_img
        cache[fullsize_key("/song.mp3")] = fullsize_img

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("wafer.app.viewer.grid.pipeline.grid_resolver", _fake_resolver())
            pipeline.schedule_render(0, "/song.mp3", QtCore.QSize(200, 200))
            _process_events_until(lambda: widget.set_image.called)

        assert widget.set_image.call_args[0][0] is fullsize_img

    def test_widget_thumbnail_uses_fullsize_cache(self, dispatcher):
        from wafer.app.viewer.grid.cachemanager import fullsize_key

        widgets = {}
        cache = _FakeCache()
        pipeline = GridPipeline(dispatcher, dispatcher, dispatcher, cache, lambda i: widgets.get(i), lambda i, n: None, _noop_appear)

        widget = MagicMock()
        widgets[0] = widget
        fullsize_img = _make_image(400, 400)
        cache[fullsize_key("/vid.mp4")] = fullsize_img

        plugin = _StubWidgetPlugin()

        load_called = {"count": 0}

        with pytest.MonkeyPatch.context() as mp:

            def fake_load(p, s=None):
                load_called["count"] += 1
                return _make_image()

            mp.setattr("wafer.app.viewer.grid.pipeline.grid_resolver", _fake_resolver(plugin, load_fn=fake_load))
            pipeline.schedule_render(0, "/vid.mp4", QtCore.QSize(300, 300))
            _process_events_until(lambda: widget.set_thumb.called)

        assert load_called["count"] == 0
        assert widget.set_thumb.call_args[0][0] is fullsize_img


class TestPipelineErrorPlaceholder:
    def test_image_plugin_shows_error_on_load_failure(self, dispatcher):
        widgets = {}
        cache = _FakeCache()
        pipeline = GridPipeline(dispatcher, dispatcher, dispatcher, cache, lambda i: widgets.get(i), lambda i, n: None, _noop_appear)

        widget = MagicMock()
        widgets[0] = widget

        class _FailPlugin:
            NAME = "fail"
            EXTENSIONS = (".png",)

            @classmethod
            def can_handle(cls, path):
                return True

            def load(self, path, size=None):
                return None

        plugin = _FailPlugin()

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("wafer.app.viewer.grid.pipeline.grid_resolver", _fake_resolver(plugin))
            pipeline.schedule_render(0, "/broken.png", QtCore.QSize(100, 100))

        _process_events_until(lambda: widget.set_image.called)
        img = widget.set_image.call_args[0][0]
        assert isinstance(img, QtGui.QImage)
        assert not img.isNull()
        assert "/broken.png" in cache

    def test_error_placeholder_is_cached_and_reused(self, dispatcher):
        widgets = {}
        cache = _FakeCache()
        pipeline = GridPipeline(dispatcher, dispatcher, dispatcher, cache, lambda i: widgets.get(i), lambda i, n: None, _noop_appear)

        widget = MagicMock()
        widgets[0] = widget

        class _FailPlugin:
            NAME = "fail2"
            EXTENSIONS = (".fail",)

            @classmethod
            def can_handle(cls, path):
                return True

            def load(self, path, size=None):
                return None

        plugin = _FailPlugin()

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("wafer.app.viewer.grid.pipeline.grid_resolver", _fake_resolver(plugin))
            pipeline.schedule_render(0, "/broken.fail", QtCore.QSize(100, 100))

        _process_events_until(lambda: widget.set_image.called)
        first_img = widget.set_image.call_args[0][0]

        widget.reset_mock()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("wafer.app.viewer.grid.pipeline.grid_resolver", _fake_resolver(plugin))
            pipeline.schedule_render(0, "/broken.fail", QtCore.QSize(100, 100))

        _process_events_until(lambda: widget.set_image.called)
        second_img = widget.set_image.call_args[0][0]
        assert second_img is first_img


class TestAppearAfterRender:
    def test_appear_called_after_render_on_resolve(self, dispatcher):
        call_order = []
        widgets = {}
        cache = _FakeCache()

        class _TrackPlugin(WidgetGridPlugin):
            NAME = "track"
            EXTENSIONS = (".mp4",)
            WIDGET_CLASS = MagicMock
            REQUIRE_THUMBNAIL = False
            PRIORITY = 5

            def render(self, widget, path, size):
                widget._path = path
                call_order.append("render")

        def appear_fn(index):
            call_order.append("appear")

        plugin = _TrackPlugin()
        pipeline = GridPipeline(
            dispatcher, dispatcher, dispatcher, cache,
            lambda i: widgets.get(i), lambda i, n: None, appear_fn,
        )

        widget = MagicMock()
        widget._path = None
        widgets[0] = widget

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("wafer.app.viewer.grid.pipeline.grid_resolver", _fake_resolver(plugin))
            pipeline.schedule_render(0, "/test.mp4", QtCore.QSize(200, 200))
            _process_events_until(lambda: len(call_order) >= 2)

        assert call_order == ["render", "appear"]

    def test_dispatch_widget_render_does_not_call_appear(self, dispatcher):
        call_order = []
        widgets = {}
        cache = _FakeCache()

        class _TrackPlugin2(WidgetGridPlugin):
            NAME = "track2"
            EXTENSIONS = (".mp4",)
            WIDGET_CLASS = MagicMock
            REQUIRE_THUMBNAIL = False
            PRIORITY = 5

            def render(self, widget, path, size):
                call_order.append("render")

        def appear_fn(index):
            call_order.append("appear")

        plugin = _TrackPlugin2()
        pipeline = GridPipeline(
            dispatcher, dispatcher, dispatcher, cache,
            lambda i: widgets.get(i), lambda i, n: None, appear_fn,
        )

        widget = MagicMock()
        widgets[0] = widget

        pipeline.schedule_render(0, "/test.mp4", QtCore.QSize(200, 200), plugin)
        _process_events_until(lambda: len(call_order) >= 1, timeout_ms=3000)
        assert call_order == ["render"]
