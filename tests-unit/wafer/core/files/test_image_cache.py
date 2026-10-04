import pytest
from PySide6 import QtGui
from wafer.core.files.image_cache import MemoryLimitedImageCache


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


def test_get_if_sufficient_returns_image_when_large_enough(cache):
    from PySide6 import QtCore

    cache["k"] = _make_image(200, 100)
    result = cache.get_if_sufficient("k", QtCore.QSize(200, 100))
    assert result is not None
    assert result.width() == 200


def test_get_if_sufficient_returns_default_when_too_small(cache):
    from PySide6 import QtCore

    cache["k"] = _make_image(50, 50)
    assert cache.get_if_sufficient("k", QtCore.QSize(100, 100)) is None
    assert cache.get_if_sufficient("k", QtCore.QSize(100, 100), 42) == 42
    assert cache.get_if_sufficient("missing", QtCore.QSize(10, 10)) is None


def test_get_if_sufficient_updates_lru(cache):
    from PySide6 import QtCore

    size_per = 100 * 100 * 4
    max_count = cache.max_bytes // size_per

    for i in range(max_count):
        cache[f"img_{i}"] = _make_image(100, 100)

    cache.get_if_sufficient("img_0", QtCore.QSize(50, 50))

    for i in range(max_count, max_count + 2):
        cache[f"img_{i}"] = _make_image(100, 100)

    assert "img_0" in cache
    assert "img_1" not in cache


def test_peek_if_sufficient_returns_image_when_large_enough(cache):
    from PySide6 import QtCore

    cache["k"] = _make_image(200, 100)
    result = cache.peek_if_sufficient("k", QtCore.QSize(200, 100))
    assert result is not None
    assert result.width() == 200


def test_peek_if_sufficient_returns_default_when_too_small(cache):
    from PySide6 import QtCore

    cache["k"] = _make_image(50, 50)
    assert cache.peek_if_sufficient("k", QtCore.QSize(100, 100)) is None
    assert cache.peek_if_sufficient("k", QtCore.QSize(100, 100), 42) == 42


def test_peek_if_sufficient_does_not_update_lru(cache):
    from PySide6 import QtCore

    size_per = 100 * 100 * 4
    max_count = cache.max_bytes // size_per

    for i in range(max_count):
        cache[f"img_{i}"] = _make_image(100, 100)

    cache.peek_if_sufficient("img_0", QtCore.QSize(50, 50))

    for i in range(max_count, max_count + 2):
        cache[f"img_{i}"] = _make_image(100, 100)

    assert "img_0" not in cache
