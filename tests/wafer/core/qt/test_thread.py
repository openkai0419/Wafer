import pytest
from PySide6 import QtCore, QtWidgets
from wafer.core.qt.thread import (
    AdaptiveThreadPool, SimpleThreadPool,
    grid_thumb_pool, grid_render_pool, utility_pool, _HALVE_SENTINEL,
)


def test_adaptive_pool_is_independent():
    a = AdaptiveThreadPool('test_a', base_limit=2)
    b = AdaptiveThreadPool('test_b', base_limit=3)
    assert a is not b
    assert a.pool is not b.pool
    assert a.base_limit == 2
    assert b.base_limit == 3


def test_adaptive_thread_pool_limits():
    pool = AdaptiveThreadPool('test_limits', base_limit=2)
    assert pool.base_limit >= 1
    assert pool.max_limit >= pool.base_limit


def test_on_delta_increase():
    pool = AdaptiveThreadPool('test_inc', base_limit=2)
    pool.pool.setMaxThreadCount(pool.base_limit)
    pool._on_delta_requested(+1)
    new_count = pool.pool.maxThreadCount()
    assert new_count == min(pool.base_limit + 1, pool.max_limit)


def test_on_delta_decrease_clamped():
    pool = AdaptiveThreadPool('test_dec', base_limit=2)
    pool.pool.setMaxThreadCount(pool.base_limit)
    pool._on_delta_requested(-1)
    assert pool.pool.maxThreadCount() == pool.base_limit


def test_on_delta_zero():
    pool = AdaptiveThreadPool('test_zero', base_limit=2)
    original = pool.pool.maxThreadCount()
    pool._on_delta_requested(0)
    assert pool.pool.maxThreadCount() == original


def test_on_delta_halve():
    pool = AdaptiveThreadPool('test_halve', base_limit=2)
    pool.pool.setMaxThreadCount(8)
    pool._on_delta_requested(_HALVE_SENTINEL)
    result = pool.pool.maxThreadCount()
    assert result <= 8
    assert result >= pool.base_limit


def test_start_runnable_direct():
    class _TestRunnable(QtCore.QRunnable):
        def __init__(self):
            super().__init__()
            self.result = None
        def run(self):
            self.result = 10 + 20
    r = _TestRunnable()
    r.run()
    assert r.result == 30


def test_pool_submit_does_not_raise():
    pool = AdaptiveThreadPool('test_submit', base_limit=2)
    class _TestRunnable(QtCore.QRunnable):
        def run(self):
            pass
    pool.submit(_TestRunnable())


def test_named_pool_instances_are_distinct():
    assert grid_thumb_pool is not grid_render_pool
    assert grid_thumb_pool.pool is not grid_render_pool.pool
    assert grid_thumb_pool.pool is not utility_pool.pool


def test_simple_thread_pool_submit():
    pool = SimpleThreadPool('test_simple')
    class _TestRunnable(QtCore.QRunnable):
        def run(self):
            pass
    pool.submit(_TestRunnable())


def test_simple_thread_pool_default_max():
    pool = SimpleThreadPool('test_default')
    assert pool.pool.maxThreadCount() == QtCore.QThread.idealThreadCount()
