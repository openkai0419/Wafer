import threading
import time

import pytest
from PySide6 import QtCore, QtWidgets
from wafer.core.qt.dispatcher import Dispatcher, CancelToken


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


class TestCancelToken:
    def test_initial_state(self):
        token = CancelToken()
        assert not token.is_cancelled()

    def test_set(self):
        token = CancelToken()
        token.cancel()
        assert token.is_cancelled()

    def test_thread_safe(self):
        token = CancelToken()
        results = []

        def worker():
            time.sleep(0.01)
            token.cancel()

        t = threading.Thread(target=worker)
        t.start()
        t.join()
        assert token.is_cancelled()


class TestDispatcherPost:
    def test_post_executes_on_bg_thread(self, dispatcher):
        result = {}

        def task():
            result['tid'] = threading.current_thread().ident

        dispatcher.post(task)
        _process_events_until(lambda: 'tid' in result)
        assert 'tid' in result
        assert result['tid'] != threading.main_thread().ident

    def test_post_with_cancel_skips(self, dispatcher):
        result = {'called': False}
        cancel = CancelToken()
        cancel.cancel()

        def task():
            result['called'] = True

        dispatcher.post(task, cancel=cancel)
        time.sleep(0.2)
        QtWidgets.QApplication.instance().processEvents()
        assert not result['called']

    def test_post_with_priority(self, dispatcher):
        order = []
        barrier = threading.Event()

        def blocker():
            barrier.wait(timeout=2)

        def make_task(label):
            def task():
                order.append(label)
            return task

        dispatcher.post(blocker, priority=0)
        time.sleep(0.05)
        dispatcher.post(make_task('low'), priority=1)
        dispatcher.post(make_task('high'), priority=9)
        barrier.set()
        _process_events_until(lambda: len(order) >= 2)
        assert 'high' in order
        assert 'low' in order

    def test_post_exception_does_not_crash(self, dispatcher):
        done = {'ok': False}

        def bad_task():
            raise RuntimeError("test error")

        def good_task():
            done['ok'] = True

        dispatcher.post(bad_task)
        dispatcher.post(good_task)
        _process_events_until(lambda: done['ok'])
        assert done['ok']


class TestDispatcherInvoke:
    def test_invoke_runs_on_main_thread(self, dispatcher):
        result = {}

        def callback():
            result['tid'] = threading.current_thread().ident

        dispatcher.invoke(callback)
        _process_events_until(lambda: 'tid' in result)
        assert result['tid'] == threading.main_thread().ident

    def test_invoke_from_bg_thread(self, dispatcher):
        result = {}

        def bg_task():
            dispatcher.invoke(lambda: result.update({'tid': threading.current_thread().ident}))

        dispatcher.post(bg_task)
        _process_events_until(lambda: 'tid' in result)
        assert result['tid'] == threading.main_thread().ident

    def test_invoke_preserves_order(self, dispatcher):
        order = []

        for i in range(5):
            val = i
            dispatcher.invoke(lambda v=val: order.append(v))

        _process_events_until(lambda: len(order) >= 5)
        assert order == [0, 1, 2, 3, 4]

    def test_invoke_exception_does_not_crash(self, dispatcher):
        done = {'ok': False}

        dispatcher.invoke(lambda: (_ for _ in ()).throw(RuntimeError("test")))
        dispatcher.invoke(lambda: done.update({'ok': True}))
        _process_events_until(lambda: done['ok'])
        assert done['ok']


class TestDispatcherIntegration:
    def test_post_then_invoke_roundtrip(self, dispatcher):
        result = {}

        def bg_task():
            result['computed'] = 42
            dispatcher.invoke(lambda: result.update({'main_tid': threading.current_thread().ident}))

        dispatcher.post(bg_task)
        _process_events_until(lambda: 'main_tid' in result)
        assert result['computed'] == 42
        assert result['main_tid'] == threading.main_thread().ident

    def test_cancel_token_with_post_invoke_flow(self, dispatcher):
        cancel = CancelToken()
        result = {'invoked': False}

        def bg_task():
            if cancel.is_cancelled():
                return
            time.sleep(0.1)
            if cancel.is_cancelled():
                return
            dispatcher.invoke(lambda: result.update({'invoked': True}))

        cancel.cancel()
        dispatcher.post(bg_task, cancel=cancel)
        time.sleep(0.3)
        QtWidgets.QApplication.instance().processEvents()
        assert not result['invoked']
