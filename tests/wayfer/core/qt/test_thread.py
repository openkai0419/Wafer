import time
import pytest
from PySide6 import QtCore, QtWidgets
from wayfer.core.qt.thread import CancellableRunnable, AdaptiveThreadPool


class _SumRunnable(CancellableRunnable):
    def __init__(self, a, b):
        super().__init__()
        self.a = a
        self.b = b

    def execute(self):
        return self.a + self.b


class _ErrorRunnable(CancellableRunnable):
    def execute(self):
        raise ValueError("intentional error")


class _SlowRunnable(CancellableRunnable):
    def execute(self):
        time.sleep(0.5)
        return "done"


def test_cancellable_runnable_execute():
    r = _SumRunnable(3, 4)
    received = []
    r.signals.finished.connect(lambda v: received.append(v))
    r.run()
    assert received == [7]


def test_cancellable_runnable_cancelled():
    r = _SumRunnable(1, 2)
    r.cancel()
    received = []
    r.signals.finished.connect(lambda v: received.append(v))
    r.run()
    assert received == []


def test_cancellable_runnable_error_does_not_emit():
    r = _ErrorRunnable()
    received = []
    r.signals.finished.connect(lambda v: received.append(v))
    r.run()
    assert received == []


def test_adaptive_thread_pool_singleton():
    a = AdaptiveThreadPool()
    b = AdaptiveThreadPool()
    assert a is b


def test_adaptive_thread_pool_limits():
    pool = AdaptiveThreadPool()
    assert pool.base_limit >= 1
    assert pool.max_limit >= pool.base_limit


def test_on_delta_increase():
    pool = AdaptiveThreadPool()
    original = pool.pool.maxThreadCount()
    pool.pool.setMaxThreadCount(pool.base_limit)
    pool._on_delta_requested(+1)
    new_count = pool.pool.maxThreadCount()
    assert new_count == min(pool.base_limit + 1, pool.max_limit)
    pool.pool.setMaxThreadCount(original)


def test_on_delta_decrease_clamped():
    pool = AdaptiveThreadPool()
    original = pool.pool.maxThreadCount()
    pool.pool.setMaxThreadCount(pool.base_limit)
    pool._on_delta_requested(-1)
    assert pool.pool.maxThreadCount() == pool.base_limit
    pool.pool.setMaxThreadCount(original)


def test_on_delta_zero():
    pool = AdaptiveThreadPool()
    original = pool.pool.maxThreadCount()
    pool._on_delta_requested(0)
    assert pool.pool.maxThreadCount() == original


def test_on_delta_halve():
    pool = AdaptiveThreadPool()
    original = pool.pool.maxThreadCount()
    pool.pool.setMaxThreadCount(8)
    pool._on_delta_requested(AdaptiveThreadPool._HALVE_SENTINEL)
    result = pool.pool.maxThreadCount()
    assert result <= 8
    assert result >= pool.base_limit
    pool.pool.setMaxThreadCount(original)


def test_start_runnable_direct():
    r = _SumRunnable(10, 20)
    received = []
    r.signals.finished.connect(lambda v: received.append(v))
    r.run()
    assert received == [30]


def test_pool_start_does_not_raise():
    pool = AdaptiveThreadPool()
    r = _SumRunnable(1, 2)
    pool.submit(r)


def test_singleton_init_not_reset():
    pool = AdaptiveThreadPool()
    original_base = pool.base_limit
    original_proxy = pool._proxy
    pool2 = AdaptiveThreadPool()
    assert pool2 is pool
    assert pool2.base_limit == original_base
    assert pool2._proxy is original_proxy
