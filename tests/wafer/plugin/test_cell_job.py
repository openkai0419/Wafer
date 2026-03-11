import threading
import time

import pytest
from PySide6 import QtCore, QtWidgets
from wafer.core.qt.dispatcher import Dispatcher, CancelToken
from wafer.plugin.grid.cell_job import CellJob


@pytest.fixture()
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


@pytest.fixture()
def dispatcher(qapp):
    return Dispatcher()


def _process_events_until(predicate, timeout_ms=3000):
    app = QtWidgets.QApplication.instance()
    deadline = time.monotonic() + timeout_ms / 1000.0
    while not predicate() and time.monotonic() < deadline:
        app.processEvents(QtCore.QEventLoop.AllEvents, 50)
        time.sleep(0.01)


class FakeCache:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def put(self, key, value):
        self.store[key] = value


class TestCellJobAttributes:
    def test_fields(self, dispatcher):
        cancel = CancelToken()
        cache = FakeCache()
        job = CellJob(
            index=5,
            path="/test/image.png",
            size=QtCore.QSize(100, 100),
            image_cache=cache,
            cancel=cancel,
            dispatcher=dispatcher,
            widget_lookup=lambda idx: None,
        )
        assert job.index == 5
        assert job.path == "/test/image.png"
        assert job.size == QtCore.QSize(100, 100)
        assert job.image_cache is cache


class TestCellJobCancel:
    def test_not_cancelled_initially(self, dispatcher):
        cancel = CancelToken()
        job = CellJob(0, "", QtCore.QSize(), None, cancel, dispatcher, lambda i: None)
        assert not job.is_cancelled()

    def test_cancelled_after_set(self, dispatcher):
        cancel = CancelToken()
        job = CellJob(0, "", QtCore.QSize(), None, cancel, dispatcher, lambda i: None)
        cancel.set()
        assert job.is_cancelled()


class TestCellJobInvoke:
    def test_invoke_calls_fn_with_widget(self, dispatcher):
        cancel = CancelToken()
        widget = {"value": 0}
        result = {}

        def lookup(idx):
            if idx == 3:
                return widget
            return None

        job = CellJob(3, "/a.png", QtCore.QSize(50, 50), None, cancel, dispatcher, lookup)
        job.invoke(lambda w: result.update({"widget": w}))
        _process_events_until(lambda: 'widget' in result)
        assert result['widget'] is widget

    def test_invoke_skips_when_cancelled(self, dispatcher):
        cancel = CancelToken()
        cancel.set()
        result = {'called': False}

        job = CellJob(0, "", QtCore.QSize(), None, cancel, dispatcher, lambda i: "w")
        job.invoke(lambda w: result.update({'called': True}))
        time.sleep(0.1)
        QtWidgets.QApplication.instance().processEvents()
        assert not result['called']

    def test_invoke_skips_when_widget_is_none(self, dispatcher):
        cancel = CancelToken()
        result = {'called': False}

        job = CellJob(0, "", QtCore.QSize(), None, cancel, dispatcher, lambda i: None)
        job.invoke(lambda w: result.update({'called': True}))
        time.sleep(0.1)
        QtWidgets.QApplication.instance().processEvents()
        assert not result['called']

    def test_invoke_runs_on_main_thread(self, dispatcher):
        cancel = CancelToken()
        result = {}

        job = CellJob(0, "", QtCore.QSize(), None, cancel, dispatcher, lambda i: "w")
        job.invoke(lambda w: result.update({'tid': threading.current_thread().ident}))
        _process_events_until(lambda: 'tid' in result)
        assert result['tid'] == threading.main_thread().ident

    def test_invoke_multiple_times(self, dispatcher):
        cancel = CancelToken()
        order = []

        job = CellJob(0, "", QtCore.QSize(), None, cancel, dispatcher, lambda i: "w")
        job.invoke(lambda w: order.append(1))
        job.invoke(lambda w: order.append(2))
        job.invoke(lambda w: order.append(3))
        _process_events_until(lambda: len(order) >= 3)
        assert order == [1, 2, 3]

    def test_invoke_cancelled_between_calls(self, dispatcher):
        cancel = CancelToken()
        result = {'first': False, 'second': False}

        job = CellJob(0, "", QtCore.QSize(), None, cancel, dispatcher, lambda i: "w")
        job.invoke(lambda w: result.update({'first': True}))
        _process_events_until(lambda: result['first'])
        cancel.set()
        job.invoke(lambda w: result.update({'second': True}))
        time.sleep(0.1)
        QtWidgets.QApplication.instance().processEvents()
        assert result['first']
        assert not result['second']


class TestCellJobIntegration:
    def test_bg_task_with_invoke(self, dispatcher):
        cancel = CancelToken()
        cache = FakeCache()
        result = {}

        def lookup(idx):
            return result

        job = CellJob(0, "/bg.png", QtCore.QSize(200, 200), image_cache=cache, cancel=cancel, dispatcher=dispatcher, widget_lookup=lookup)

        def bg_task():
            value = 42
            cache.put(job.path, value)
            if job.is_cancelled():
                return
            job.invoke(lambda w: w.update({'rendered': cache.get(job.path)}))

        dispatcher.post(bg_task)
        _process_events_until(lambda: 'rendered' in result)
        assert result['rendered'] == 42
        assert cache.get("/bg.png") == 42
