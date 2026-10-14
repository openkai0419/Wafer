from PySide6 import QtCore, QtGui, QtWidgets

from extensions.mapping import map_host
from extensions.mapping.map_host import MapHost, hover_bucket, thumb_bucket


def make_host(qtbot):
    parent = QtWidgets.QWidget()
    qtbot.addWidget(parent)
    return MapHost(parent)


def test_buckets():
    assert thumb_bucket(10) == 64 and thumb_bucket(100) == 128 and thumb_bucket(999) == 256
    assert hover_bucket(200) == 256 and hover_bucket(2000) == 1024


def test_context_uses_sources(qtbot):
    host = make_host(qtbot)
    host.sources = {"a.zip::x.png": "a.zip"}
    assert host.context_for(["a.zip::x.png", "b.png"]) == {"path": "b.png", "paths": ["a.zip::x.png", "b.png"], "source": "b.png", "sources": ["a.zip", "b.png"]}
    assert host.context_for([]) == {}


def test_hover_shows_cached_small_thumbnail_then_upgrades(qtbot, monkeypatch):
    host = make_host(qtbot)
    host.thumbs.store("a.png", QtGui.QImage(8, 8, QtGui.QImage.Format_RGB32))
    requested = []
    monkeypatch.setattr(host.hover_thumbs, "request", lambda paths: requested.extend(paths))
    host.show_hover("a.png", QtCore.QPoint(300, 300))
    assert host.preview.isVisible() and requested == ["a.png"]
    host.hover_thumbs.store("a.png", QtGui.QImage(256, 256, QtGui.QImage.Format_RGB32))
    assert host.preview.isVisible()
    host.hide_hover()
    assert not host.preview.isVisible()


def test_hover_disabled_when_size_zero(qtbot):
    host = make_host(qtbot)
    host.hover_size = 0
    host.show_hover("a.png", QtCore.QPoint(1, 1))
    assert not host.preview.isVisible()


def test_hover_on_same_pixmap_only_moves_the_window(qtbot, monkeypatch):
    host = make_host(qtbot)
    host.hover_thumbs.store("a.png", QtGui.QImage(32, 32, QtGui.QImage.Format_RGB32))
    host.show_hover("a.png", QtCore.QPoint(300, 300))
    shown = []
    monkeypatch.setattr(host.preview, "show_image", lambda *args: shown.append(args))
    host.show_hover("a.png", QtCore.QPoint(320, 310))
    assert shown == []
    assert host.hover_cursor == QtCore.QPoint(320, 310)
    host.show_hover("b.png", QtCore.QPoint(320, 310))
    assert len(shown) == 1


def test_late_hover_thumbnail_for_other_path_is_ignored(qtbot):
    host = make_host(qtbot)
    host.show_hover("a.png", QtCore.QPoint(300, 300))
    host.hide_hover()
    host.hover_thumbs.store("a.png", QtGui.QImage(16, 16, QtGui.QImage.Format_RGB32))
    assert not host.preview.isVisible()


def test_display_size_picks_thumbnail_bucket(qtbot):
    host = make_host(qtbot)
    host.set_display_size(100)
    assert host.thumbs.size == 128
    host.set_display_size(5)
    assert host.thumbs.size == map_host.THUMB_BUCKETS[0]


def test_hover_size_zero_hides_preview(qtbot):
    host = make_host(qtbot)
    host.show_hover("a.png", QtCore.QPoint(300, 300))
    host.set_hover_size(0)
    assert not host.preview.isVisible()
    host.set_hover_size(512)
    assert host.hover_thumbs.size == 512


def test_cache_limits_follow_the_pixel_budget(qtbot, monkeypatch):
    monkeypatch.setattr(map_host, "dpix", lambda value: value * 2)
    host = make_host(qtbot)
    assert host.thumbs.cache_limit == map_host.THUMB_BUDGET // (128 * 128 * 4)
    host.set_display_size(200)
    assert host.thumbs.size == 256 and host.thumbs.cache_limit == map_host.THUMB_BUDGET // (512 * 512 * 4)
    host.set_hover_size(1024)
    assert host.hover_thumbs.cache_limit == map_host.HOVER_BUDGET // (2048 * 2048 * 4)
    assert map_host.cache_limit(1, 1024) == 1
