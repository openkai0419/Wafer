from wafer.qt.common.thread import AdaptiveThreadPool, _HALVE_SENTINEL


def test_on_delta_increase():
    pool = AdaptiveThreadPool("test_inc", base_limit=2)
    pool.pool.setMaxThreadCount(pool.base_limit)
    pool._on_delta_requested(+1)
    new_count = pool.pool.maxThreadCount()
    assert new_count == min(pool.base_limit + 1, pool.max_limit)


def test_on_delta_decrease_clamped():
    pool = AdaptiveThreadPool("test_dec", base_limit=2)
    pool.pool.setMaxThreadCount(pool.base_limit)
    pool._on_delta_requested(-1)
    assert pool.pool.maxThreadCount() == pool.base_limit


def test_on_delta_zero():
    pool = AdaptiveThreadPool("test_zero", base_limit=2)
    original = pool.pool.maxThreadCount()
    pool._on_delta_requested(0)
    assert pool.pool.maxThreadCount() == original


def test_on_delta_halve():
    pool = AdaptiveThreadPool("test_halve", base_limit=2)
    pool.pool.setMaxThreadCount(8)
    pool._on_delta_requested(_HALVE_SENTINEL)
    result = pool.pool.maxThreadCount()
    assert result <= 8
    assert result >= pool.base_limit
