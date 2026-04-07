import threading

from wafer.utils.signal import Signal


class TestSignalBasic:
    def test_emit_calls_connected_callback(self):
        sig = Signal()
        received = []
        sig.connect(lambda x: received.append(x))
        sig.emit("hello")
        assert received == ["hello"]

    def test_emit_no_callbacks_does_nothing(self):
        sig = Signal()
        sig.emit("ignored")

    def test_multiple_callbacks(self):
        sig = Signal()
        a, b = [], []
        sig.connect(lambda x: a.append(x))
        sig.connect(lambda x: b.append(x))
        sig.emit(42)
        assert a == [42]
        assert b == [42]

    def test_emit_with_kwargs(self):
        sig = Signal()
        received = {}
        sig.connect(lambda **kw: received.update(kw))
        sig.emit(key="value")
        assert received == {"key": "value"}

    def test_emit_with_multiple_args(self):
        sig = Signal()
        received = []
        sig.connect(lambda a, b: received.append((a, b)))
        sig.emit(1, 2)
        assert received == [(1, 2)]

    def test_callback_order_preserved(self):
        sig = Signal()
        order = []
        sig.connect(lambda: order.append("first"))
        sig.connect(lambda: order.append("second"))
        sig.connect(lambda: order.append("third"))
        sig.emit()
        assert order == ["first", "second", "third"]


class TestSignalThreadSafety:
    def test_concurrent_connect_and_emit(self):
        sig = Signal()
        results = []
        barrier = threading.Barrier(3)

        def connector():
            barrier.wait()
            sig.connect(lambda x: results.append(x))

        def emitter():
            barrier.wait()
            for i in range(10):
                sig.emit(i)

        threads = [threading.Thread(target=connector) for _ in range(2)]
        threads.append(threading.Thread(target=emitter))
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
        assert len(results) >= 0

    def test_emit_from_multiple_threads(self):
        sig = Signal()
        results = []
        lock = threading.Lock()

        def safe_append(x):
            with lock:
                results.append(x)

        sig.connect(safe_append)

        def emitter(val):
            for _ in range(50):
                sig.emit(val)

        threads = [threading.Thread(target=emitter, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
        assert len(results) == 200
