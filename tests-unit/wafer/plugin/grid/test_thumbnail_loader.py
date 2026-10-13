import threading

import pytest
from PySide6 import QtGui

from wafer.plugin.grid import thumbnail_loader
from wafer.plugin.grid.thumbnail_loader import ThumbnailLoader


def _image():
    image = QtGui.QImage(4, 4, QtGui.QImage.Format_RGB32)
    image.fill(QtGui.QColor(255, 0, 0))
    return image


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


def test_set_size_clears_cache(qtbot):
    loader = ThumbnailLoader(lambda _p: None, size=32, cache_limit=10)
    loader.store("a", _image())
    loader.set_size(64)
    assert loader.size == 64 and "a" not in loader
