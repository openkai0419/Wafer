import threading

import pytest
from PySide6 import QtGui

from wafer.plugin.grid import thumbnail_loader
from wafer.plugin.grid.thumbnail_loader import ThumbnailLoader, shared_image_cache


def _image(side=4):
    image = QtGui.QImage(side, side, QtGui.QImage.Format_RGB32)
    image.fill(QtGui.QColor(255, 0, 0))
    return image


@pytest.fixture(autouse=True)
def empty_shared_cache():
    shared_image_cache().clear()
    yield
    shared_image_cache().clear()


@pytest.fixture()
def calls(monkeypatch):
    calls = []

    def fake_load(path, size):
        calls.append((path, size.width()))
        return _image()

    monkeypatch.setattr(thumbnail_loader, "load_thumbnail", fake_load)
    return calls


def test_request_loads_and_notifies(qtbot, calls):
    loaded = []
    loader = ThumbnailLoader(loaded.append, size=32, cache_limit=10)
    loader.request(["a", "b"])
    qtbot.waitUntil(lambda: sorted(loaded) == ["a", "b"], timeout=3000)
    assert not loader.get("a").isNull()
    assert not loader.pending("a")


def test_cached_path_is_not_reloaded(qtbot, calls):
    loaded = []
    loader = ThumbnailLoader(loaded.append, size=32, cache_limit=10)
    loader.request(["a"])
    qtbot.waitUntil(lambda: loaded == ["a"], timeout=3000)
    loader.request(["a"])
    assert [c[0] for c in calls] == ["a"]


def test_null_image_is_cached_as_empty_pixmap(qtbot):
    loader = ThumbnailLoader(lambda _p: None, size=32, cache_limit=10)
    loader.store("a", None)
    assert loader.get("a").isNull()


def test_lru_eviction_and_refresh(qtbot):
    loader = ThumbnailLoader(lambda _p: None, size=32, cache_limit=3)
    for key in ("a", "b", "c"):
        loader.store(key, _image())
    loader.get("a")
    loader.store("d", _image())
    assert "a" in loader and "b" not in loader
    assert len(loader) == 3


def test_cancel_prevents_store(qtbot, monkeypatch):
    release = threading.Event()
    started = threading.Event()

    def slow_load(path, size):
        started.set()
        release.wait(3)
        return _image()

    monkeypatch.setattr(thumbnail_loader, "load_thumbnail", slow_load)
    loaded = []
    loader = ThumbnailLoader(loaded.append, size=32, cache_limit=10)
    try:
        loader.request(["a"])
        qtbot.waitUntil(started.is_set, timeout=3000)
        assert loader.pending("a")
        loader.cancel_all()
        assert not loader.pending("a")
    finally:
        release.set()
    qtbot.wait(100)
    assert loaded == [] and "a" not in loader


def test_failed_load_does_not_strand_other_paths(qtbot, monkeypatch):
    def fake_load(path, size):
        if path == "bad":
            raise ValueError("decoder failed")
        return _image()

    monkeypatch.setattr(thumbnail_loader, "load_thumbnail", fake_load)
    loaded = []
    loader = ThumbnailLoader(loaded.append, size=32, cache_limit=10)
    loader.request(["bad", "good"])
    qtbot.waitUntil(lambda: sorted(loaded) == ["bad", "good"], timeout=3000)
    assert loader.get("bad").isNull()
    assert not loader.get("good").isNull()
    assert not loader.pending("bad") and not loader.pending("good")


def test_set_size_keeps_the_cache_and_larger_images_serve_smaller_sizes(qtbot, calls, monkeypatch):
    monkeypatch.setattr(thumbnail_loader, "dpix", lambda value: value)
    loader = ThumbnailLoader(lambda _p: None, size=64, cache_limit=10)
    loader.store("a", _image(64))
    loader.set_size(32)
    assert loader.size == 32 and "a" in loader
    loader.request(["a"])
    assert calls == []
    assert loader.get("a").width() == 32 and shared_image_cache().peek("a").width() == 64


def test_smaller_image_is_shown_while_a_larger_one_loads(qtbot, calls, monkeypatch):
    monkeypatch.setattr(thumbnail_loader, "dpix", lambda value: value)
    monkeypatch.setattr(thumbnail_loader, "load_thumbnail", lambda path, size: calls.append((path, size.width())) or _image(size.width()))
    loaded = []
    loader = ThumbnailLoader(loaded.append, size=32, cache_limit=10)
    loader.store("a", _image(32))
    loader.set_size(128)
    assert loader.get("a").width() == 32
    loaded.clear()
    loader.request(["a"])
    qtbot.waitUntil(lambda: loaded == ["a"], timeout=3000)
    assert calls == [("a", 128)] and loader.get("a").width() == 128


def test_small_source_is_not_reloaded_for_larger_sizes(qtbot, calls, monkeypatch):
    monkeypatch.setattr(thumbnail_loader, "dpix", lambda value: value)
    loader = ThumbnailLoader(lambda _p: None, size=128, cache_limit=10)
    loader.store("a", _image(20), 128)
    loader.set_size(256)
    loader.request(["a"])
    assert calls == []


def test_images_are_shared_with_other_loaders_and_the_grid_cache(qtbot, calls, monkeypatch):
    monkeypatch.setattr(thumbnail_loader, "dpix", lambda value: value)
    first = ThumbnailLoader(lambda _p: None, size=64, cache_limit=10)
    second = ThumbnailLoader(lambda _p: None, size=32, cache_limit=10)
    first.store("a", _image(64))
    assert shared_image_cache().peek("a").width() == 64
    second.request(["a"])
    assert calls == [] and second.get("a").width() == 32
    shared_image_cache()["b"] = _image(48)
    second.request(["b"])
    assert calls == [] and second.get("b").width() == 32


def test_smaller_result_does_not_replace_a_larger_cached_image(qtbot, monkeypatch):
    monkeypatch.setattr(thumbnail_loader, "dpix", lambda value: value)
    loader = ThumbnailLoader(lambda _p: None, size=32, cache_limit=10)
    loader.store("a", _image(64))
    loader.store("a", _image(32))
    assert shared_image_cache().peek("a").width() == 64 and loader.get("a").width() == 32


def test_large_shared_images_are_kept_at_the_loader_size(qtbot, monkeypatch):
    monkeypatch.setattr(thumbnail_loader, "dpix", lambda value: value)
    loader = ThumbnailLoader(lambda _p: None, size=64, cache_limit=10)
    shared_image_cache()["a"] = _image(1024)
    assert loader.get("a").width() == 64
    assert loader.get("a").width() == 64 and shared_image_cache().peek("a").width() == 1024


def test_shrinking_the_size_shrinks_kept_pixmaps(qtbot, monkeypatch):
    monkeypatch.setattr(thumbnail_loader, "dpix", lambda value: value)
    loader = ThumbnailLoader(lambda _p: None, size=256, cache_limit=10)
    loader.store("a", _image(256))
    shared_image_cache().clear()
    loader.set_size(64)
    assert loader.get("a").width() == 64
