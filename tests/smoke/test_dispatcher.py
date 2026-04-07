import threading
import time

from wafer.core.qt.dispatcher import CancelToken, CancelSlot, Dispatcher


class TestCancelTokenSmoke:
    def test_initial_state(self):
        token = CancelToken()
        assert not token.is_cancelled()

    def test_cancel(self):
        token = CancelToken()
        token.cancel()
        assert token.is_cancelled()

    def test_double_cancel_safe(self):
        token = CancelToken()
        token.cancel()
        token.cancel()
        assert token.is_cancelled()

    def test_thread_safety(self):
        token = CancelToken()
        results = []

        def checker():
            while not token.is_cancelled():
                time.sleep(0.001)
            results.append(True)

        t = threading.Thread(target=checker)
        t.start()
        time.sleep(0.01)
        token.cancel()
        t.join(timeout=2.0)
        assert results == [True]


class TestCancelSlotSmoke:
    def test_renew_cancels_previous(self):
        slot = CancelSlot()
        t1 = slot.renew()
        t2 = slot.renew()
        assert t1.is_cancelled()
        assert not t2.is_cancelled()

    def test_cancel_slot(self):
        slot = CancelSlot()
        t1 = slot.renew()
        slot.cancel()
        assert t1.is_cancelled()

    def test_cancel_empty_slot(self):
        slot = CancelSlot()
        slot.cancel()

    def test_renew_returns_fresh_token(self):
        slot = CancelSlot()
        t1 = slot.renew()
        t2 = slot.renew()
        t3 = slot.renew()
        assert t1.is_cancelled()
        assert t2.is_cancelled()
        assert not t3.is_cancelled()


class TestDispatcherSmoke:
    def test_post_executes_task(self, qtbot):
        from wafer.core.qt.thread import utility_pool

        dispatcher = Dispatcher(pool=utility_pool)
        result = []
        event = threading.Event()

        def task():
            result.append(threading.current_thread().name)
            event.set()

        dispatcher.post(task)
        assert event.wait(timeout=5.0)
        assert len(result) == 1
        assert result[0] != threading.current_thread().name

    def test_post_cancelled_skips(self, qtbot):
        from wafer.core.qt.thread import utility_pool

        dispatcher = Dispatcher(pool=utility_pool)
        result = []
        token = CancelToken()
        token.cancel()

        def task():
            result.append(True)

        dispatcher.post(task, cancel=token)
        time.sleep(0.3)
        assert result == []

    def test_invoke_executes_on_main(self, qtbot):
        dispatcher = Dispatcher()
        result = []

        def on_main():
            result.append("done")

        dispatcher.invoke(on_main)
        qtbot.waitUntil(lambda: len(result) == 1, timeout=3000)
        assert result == ["done"]
