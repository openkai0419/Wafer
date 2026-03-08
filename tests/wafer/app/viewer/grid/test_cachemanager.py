import pytest
from PySide6 import QtGui, QtWidgets
from wafer.app.viewer.grid.cachemanager import MemoryLimitedImageCache, AdditionalWidgetPool
from wafer.plugin.grid.handler import grid_resolver
from wafer.plugin.grid.base import WidgetGridPlugin


def _make_image(w, h):
    return QtGui.QImage(w, h, QtGui.QImage.Format_ARGB32)


@pytest.fixture
def cache():
    c = MemoryLimitedImageCache.__wrapped__(max_mbytes=1)
    yield c
    c.clear()


def test_set_and_get(cache):
    img = _make_image(10, 10)
    cache["a"] = img
    assert "a" in cache
    assert cache["a"] is img


def test_get_missing_raises(cache):
    with pytest.raises(KeyError):
        _ = cache["missing"]


def test_contains(cache):
    assert "x" not in cache
    cache["x"] = _make_image(5, 5)
    assert "x" in cache


def test_delete(cache):
    cache["a"] = _make_image(10, 10)
    del cache["a"]
    assert "a" not in cache
    assert cache.current_bytes == 0


def test_delete_nonexistent(cache):
    del cache["nope"]
    assert cache.current_bytes == 0


def test_clear(cache):
    cache["a"] = _make_image(10, 10)
    cache["b"] = _make_image(20, 20)
    cache.clear()
    assert "a" not in cache
    assert "b" not in cache
    assert cache.current_bytes == 0


def test_get_method(cache):
    assert cache.get("missing") is None
    assert cache.get("missing", 42) == 42
    cache["k"] = _make_image(5, 5)
    assert cache.get("k") is not None


def test_peek_returns_value_without_lru_update(cache):
    size_per = 100 * 100 * 4
    max_count = cache.max_bytes // size_per

    for i in range(max_count):
        cache[f"img_{i}"] = _make_image(100, 100)

    result = cache.peek("img_0")
    assert result is not None

    for i in range(max_count, max_count + 2):
        cache[f"img_{i}"] = _make_image(100, 100)

    assert "img_0" not in cache


def test_peek_returns_default_for_missing(cache):
    assert cache.peek("missing") is None
    assert cache.peek("missing", 42) == 42


def test_lru_eviction(cache):
    small = _make_image(100, 100)
    size_per = 100 * 100 * 4
    max_count = cache.max_bytes // size_per

    for i in range(max_count + 2):
        cache[f"img_{i}"] = _make_image(100, 100)

    assert "img_0" not in cache
    assert f"img_{max_count + 1}" in cache
    assert cache.current_bytes <= cache.max_bytes


def test_access_refreshes_lru(cache):
    small = _make_image(100, 100)
    size_per = 100 * 100 * 4
    max_count = cache.max_bytes // size_per

    for i in range(max_count):
        cache[f"img_{i}"] = _make_image(100, 100)

    _ = cache["img_0"]

    for i in range(max_count, max_count + 2):
        cache[f"img_{i}"] = _make_image(100, 100)

    assert "img_0" in cache
    assert "img_1" not in cache


def test_overwrite_updates_size(cache):
    cache["a"] = _make_image(10, 10)
    old_bytes = cache.current_bytes
    cache["a"] = _make_image(20, 20)
    assert cache.current_bytes == 20 * 20 * 4


def test_current_bytes_tracking(cache):
    assert cache.current_bytes == 0
    cache["a"] = _make_image(10, 10)
    assert cache.current_bytes == 10 * 10 * 4
    cache["b"] = _make_image(5, 5)
    assert cache.current_bytes == 10 * 10 * 4 + 5 * 5 * 4
    del cache["a"]
    assert cache.current_bytes == 5 * 5 * 4


class _DummyWidget(QtWidgets.QWidget):
    pass


class _DummyGridPlugin(WidgetGridPlugin):
    NAME = 'test_dummy'
    EXTENSIONS = ('.dummy',)
    PRIORITY = 50
    WIDGET_CLASS = _DummyWidget

    def render(self, path, widget, size=None):
        pass


@pytest.fixture
def additional_pool(qtbot):
    from unittest.mock import MagicMock
    resolver = MagicMock()
    resolver.registry.get.return_value = _DummyGridPlugin
    pool = AdditionalWidgetPool(resolver)
    yield pool
    pool.reset()


def test_additional_pool_acquire_returns_widget(additional_pool, qtbot):
    parent = QtWidgets.QWidget()
    widget = additional_pool.acquire('test_dummy', parent)
    assert widget is not None
    assert isinstance(widget, _DummyWidget)
    assert widget.parent() is parent


def test_additional_pool_acquire_unknown_returns_none(qtbot):
    from unittest.mock import MagicMock
    resolver = MagicMock()
    resolver.registry.get.return_value = None
    pool = AdditionalWidgetPool(resolver)
    parent = QtWidgets.QWidget()
    assert pool.acquire('nonexistent', parent) is None


def test_additional_pool_release_and_reuse(additional_pool, qtbot):
    parent = QtWidgets.QWidget()
    w1 = additional_pool.acquire('test_dummy', parent)
    additional_pool.release(w1)
    w2 = additional_pool.acquire('test_dummy', parent)
    assert w1 is w2


def test_additional_pool_release_no_longer_calls_grid_release(qtbot):
    from unittest.mock import MagicMock
    resolver = MagicMock()
    resolver.registry.get.return_value = _DummyGridPlugin
    pool = AdditionalWidgetPool(resolver)
    parent = QtWidgets.QWidget()
    w = pool.acquire('test_dummy', parent)
    pool.release(w)
    resolver.release.assert_not_called()
    pool.reset()


def test_additional_pool_plugin_name_of(additional_pool, qtbot):
    parent = QtWidgets.QWidget()
    w = additional_pool.acquire('test_dummy', parent)
    assert additional_pool.plugin_name_of(w) == 'test_dummy'
    additional_pool.release(w)
    assert additional_pool.plugin_name_of(w) is None


def test_additional_pool_reset(additional_pool, qtbot):
    parent = QtWidgets.QWidget()
    additional_pool.acquire('test_dummy', parent)
    additional_pool.acquire('test_dummy', parent)
    additional_pool.reset()
    assert len(additional_pool._in_use) == 0
    assert all(len(v) == 0 for v in additional_pool._pools.values())


def test_additional_pool_reset_calls_cleanup(qtbot):
    from unittest.mock import MagicMock

    class _CleanableWidget(QtWidgets.QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.cleanup = MagicMock()

    class _CleanPlugin(WidgetGridPlugin):
        NAME = 'test_clean'
        EXTENSIONS = ('.clean',)
        PRIORITY = 50
        WIDGET_CLASS = _CleanableWidget

    resolver = MagicMock()
    resolver.registry.get.return_value = _CleanPlugin
    pool = AdditionalWidgetPool(resolver)
    parent = QtWidgets.QWidget()
    w = pool.acquire('test_clean', parent)
    pool.reset()
    w.cleanup.assert_called_once()


def test_additional_pool_warm_up(qtbot):
    from unittest.mock import MagicMock

    resolver = MagicMock()
    resolver.registry.list_all.return_value = [_DummyGridPlugin]
    resolver.registry.get.return_value = _DummyGridPlugin
    pool = AdditionalWidgetPool(resolver)
    parent = QtWidgets.QWidget()
    pool.warm_up(parent)
    assert 'test_dummy' in pool._pools
    assert len(pool._pools['test_dummy']) == 1
    assert isinstance(pool._pools['test_dummy'][0], _DummyWidget)


def test_additional_pool_warm_up_skips_image_plugins(qtbot):
    from unittest.mock import MagicMock
    from wafer.plugin.grid.base import ImageGridPlugin

    class _ImageLikePlugin(ImageGridPlugin):
        NAME = 'image'
        EXTENSIONS = ('.jpg',)
        PRIORITY = 50
        def load(self, path, size=None):
            return None

    resolver = MagicMock()
    resolver.registry.list_all.return_value = [_ImageLikePlugin]
    pool = AdditionalWidgetPool(resolver)
    parent = QtWidgets.QWidget()
    pool.warm_up(parent)
    assert len(pool._pools) == 0


def test_additional_pool_warm_up_skips_existing(qtbot):
    from unittest.mock import MagicMock

    resolver = MagicMock()
    resolver.registry.list_all.return_value = [_DummyGridPlugin]
    resolver.registry.get.return_value = _DummyGridPlugin
    pool = AdditionalWidgetPool(resolver)
    parent = QtWidgets.QWidget()
    pool.warm_up(parent)
    pool.warm_up(parent)
    assert len(pool._pools['test_dummy']) == 1


def test_additional_pool_size_and_in_use_count(qtbot):
    from unittest.mock import MagicMock

    resolver = MagicMock()
    resolver.registry.get.return_value = _DummyGridPlugin
    pool = AdditionalWidgetPool(resolver)
    parent = QtWidgets.QWidget()
    assert pool.pool_size('test_dummy') == 0
    assert pool.in_use_count('test_dummy') == 0
    w = pool.acquire('test_dummy', parent)
    assert pool.in_use_count('test_dummy') == 1
    pool.release(w)
    assert pool.pool_size('test_dummy') == 1
    assert pool.in_use_count('test_dummy') == 0
    pool.reset()
