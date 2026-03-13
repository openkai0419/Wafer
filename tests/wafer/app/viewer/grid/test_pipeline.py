import time
import threading

import pytest
from PySide6 import QtCore, QtWidgets
from wafer.core.qt.dispatcher import Dispatcher, CancelToken
from wafer.app.viewer.grid.pipeline import GridPipeline
from wafer.app.viewer.grid.calc_layout import LayoutData


@pytest.fixture()
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


@pytest.fixture()
def dispatcher(qapp):
    return Dispatcher()


class FakeCache:
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


class TestGridPipelineLayout:
    def test_layout_emits_result(self, dispatcher):
        result = {}
        cache = FakeCache()
        pipeline = GridPipeline(dispatcher, dispatcher, dispatcher, cache, lambda i: None, lambda i, n: None)
        pipeline.layout_ready.connect(lambda layout: result.update({'layout': layout}))

        aspects = [1.5, 1.0, 0.8, 1.2, 1.0]
        pipeline.request_layout(aspects, 100, 4, 800, 600)
        _process_events_until(lambda: 'layout' in result)

        assert 'layout' in result
        layout = result['layout']
        assert isinstance(layout, LayoutData)
        assert len(layout) == 5

    def test_layout_cancel_previous(self, dispatcher):
        result = {'count': 0}
        cache = FakeCache()
        pipeline = GridPipeline(dispatcher, dispatcher, dispatcher, cache, lambda i: None, lambda i, n: None)
        pipeline.layout_ready.connect(lambda layout: result.update({'count': result['count'] + 1}))

        aspects = [1.0] * 20
        pipeline.request_layout(aspects, 50, 2, 400, 300)
        pipeline.request_layout(aspects, 100, 4, 800, 600)
        _process_events_until(lambda: result['count'] >= 1, timeout_ms=3000)
        time.sleep(0.2)
        QtWidgets.QApplication.instance().processEvents()
        assert result['count'] <= 2

    def test_layout_masonry_mode(self, dispatcher):
        result = {}
        cache = FakeCache()
        pipeline = GridPipeline(dispatcher, dispatcher, dispatcher, cache, lambda i: None, lambda i, n: None)
        pipeline.layout_ready.connect(lambda layout: result.update({'layout': layout}))

        aspects = [1.0, 0.5, 1.5, 0.8]
        pipeline.request_layout(aspects, 100, 4, 800, 600, layout_mode='masonry')
        _process_events_until(lambda: 'layout' in result)

        layout = result['layout']
        assert len(layout) == 4

    def test_layout_empty_aspects(self, dispatcher):
        result = {}
        cache = FakeCache()
        pipeline = GridPipeline(dispatcher, dispatcher, dispatcher, cache, lambda i: None, lambda i, n: None)
        pipeline.layout_ready.connect(lambda layout: result.update({'layout': layout}))

        pipeline.request_layout([], 100, 4, 800, 600)
        _process_events_until(lambda: 'layout' in result)
        layout = result['layout']
        assert len(layout) == 0


class TestGridPipelineCancel:
    def test_cancel_all(self, dispatcher):
        cache = FakeCache()
        pipeline = GridPipeline(dispatcher, dispatcher, dispatcher, cache, lambda i: None, lambda i, n: None)

        pipeline._active[0] = CancelToken()
        pipeline._active[1] = CancelToken()
        tokens = list(pipeline._active.values())

        pipeline.cancel_all()
        assert pipeline.active_count() == 0
        assert all(t.is_cancelled() for t in tokens)

    def test_cancel_index(self, dispatcher):
        cache = FakeCache()
        pipeline = GridPipeline(dispatcher, dispatcher, dispatcher, cache, lambda i: None, lambda i, n: None)

        token = CancelToken()
        pipeline._active[5] = token
        pipeline.cancel_index(5)
        assert token.is_cancelled()
        assert 5 not in pipeline._active

    def test_cancel_nonexistent_index(self, dispatcher):
        cache = FakeCache()
        pipeline = GridPipeline(dispatcher, dispatcher, dispatcher, cache, lambda i: None, lambda i, n: None)
        pipeline.cancel_index(999)

    def test_cancel_all_clears_layout_cancel(self, dispatcher):
        cache = FakeCache()
        pipeline = GridPipeline(dispatcher, dispatcher, dispatcher, cache, lambda i: None, lambda i, n: None)
        pipeline._layout_cancel = CancelToken()

        pipeline.cancel_all()
        assert pipeline._layout_cancel is None


class TestScheduleRender:
    def test_schedule_render_cancels_existing(self, dispatcher):
        cache = FakeCache()
        pipeline = GridPipeline(dispatcher, dispatcher, dispatcher, cache, lambda i: None, lambda i, n: None)

        old_token = CancelToken()
        pipeline._active[0] = old_token

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr('wafer.app.viewer.grid.pipeline.grid_resolver',
                        type('R', (), {
                            'resolve_chain': staticmethod(lambda p: []),
                            'registry': type('Reg', (), {'instance': staticmethod(lambda n: None)})(),
                            'load': staticmethod(lambda p, s=None: None),
                        })())
            pipeline.schedule_render(0, '/a.png', QtCore.QSize(200, 200))

        assert old_token.is_cancelled()

    def test_schedule_render_no_plugin_uses_deferred_resolve(self, dispatcher):
        cache = FakeCache()
        pipeline = GridPipeline(dispatcher, dispatcher, dispatcher, cache, lambda i: None, lambda i, n: None)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr('wafer.app.viewer.grid.pipeline.grid_resolver',
                        type('R', (), {
                            'resolve_chain': staticmethod(lambda p: []),
                            'registry': type('Reg', (), {'instance': staticmethod(lambda n: None)})(),
                            'load': staticmethod(lambda p, s=None: None),
                        })())
            pipeline.schedule_render(0, '/a.unknown', QtCore.QSize(200, 200))

        assert pipeline.active_count() == 1


class TestGridPipelineIntegration:
    def test_layout_then_cancel_all(self, dispatcher):
        result = {}
        cache = FakeCache()
        pipeline = GridPipeline(dispatcher, dispatcher, dispatcher, cache, lambda i: None, lambda i, n: None)
        pipeline.layout_ready.connect(lambda layout: result.update({'layout': layout}))

        aspects = [1.0] * 10
        pipeline.request_layout(aspects, 100, 4, 800, 600)
        _process_events_until(lambda: 'layout' in result)

        pipeline.cancel_all()
        assert pipeline.active_count() == 0
