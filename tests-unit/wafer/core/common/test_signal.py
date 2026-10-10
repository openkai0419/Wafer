import threading

from wafer.core.common.signal import Signal


def test_connect_and_emit():
    sig = Signal()
    received = []
    sig.connect(lambda x: received.append(x))
    sig.emit(42)
    assert received == [42]


def test_multiple_callbacks():
    sig = Signal()
    a, b = [], []
    sig.connect(lambda x: a.append(x))
    sig.connect(lambda x: b.append(x))
    sig.emit("hello")
    assert a == ["hello"]
    assert b == ["hello"]


def test_emit_no_callbacks():
    sig = Signal()
    sig.emit(1, 2, 3)


def test_emit_with_kwargs():
    sig = Signal()
    received = []
    sig.connect(lambda **kw: received.append(kw))
    sig.emit(key="val")
    assert received == [{"key": "val"}]


def test_emit_multiple_args():
    sig = Signal()
    received = []
    sig.connect(lambda a, b: received.append((a, b)))
    sig.emit(1, 2)
    assert received == [(1, 2)]


def test_emit_preserves_order():
    sig = Signal()
    order = []
    sig.connect(lambda: order.append(1))
    sig.connect(lambda: order.append(2))
    sig.connect(lambda: order.append(3))
    sig.emit()
    assert order == [1, 2, 3]


def _run_all(threads):
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)
    assert not any(t.is_alive() for t in threads)


def test_concurrent_connect_and_emit():
    sig = Signal()
    results = []
    lock = threading.Lock()
    barrier = threading.Barrier(3)

    def append(x):
        with lock:
            results.append(x)

    def connector():
        barrier.wait()
        sig.connect(append)

    def emitter():
        barrier.wait()
        for i in range(10):
            sig.emit(i)

    _run_all([threading.Thread(target=connector) for _ in range(2)] + [threading.Thread(target=emitter)])
    results.clear()
    sig.emit("after")
    assert results == ["after", "after"]


def test_emit_from_multiple_threads():
    sig = Signal()
    results = []
    lock = threading.Lock()

    def append(x):
        with lock:
            results.append(x)

    sig.connect(append)

    def emitter(val):
        for _ in range(50):
            sig.emit(val)

    _run_all([threading.Thread(target=emitter, args=(i,)) for i in range(4)])
    assert len(results) == 200
