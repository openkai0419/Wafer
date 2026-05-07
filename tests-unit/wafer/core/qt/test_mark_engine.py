from PySide6 import QtCore, QtGui

import pytest

from wafer.core.qt.mark_engine import (
    default_mark_key,
    draw_overflow_badge,
    has_mark,
    mark_draw,
    mark_keys,
    mark_pixmap,
    normalize_mark_key,
    register_mark,
)


@pytest.fixture(autouse=True)
def _ensure_qapp(qtbot):
    pass


def _draw_test_mark(painter: QtGui.QPainter, rect: QtCore.QRectF, color: QtGui.QColor):
    painter.setPen(QtCore.Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawRect(rect)


def test_register_mark_adds_key():
    register_mark("__test_mark_engine_rect__", _draw_test_mark)
    assert "__test_mark_engine_rect__" in mark_keys()
    assert has_mark("__test_mark_engine_rect__")


def test_normalize_mark_key_falls_back_to_registered_default():
    assert normalize_mark_key("nonexistent") == default_mark_key()
    assert normalize_mark_key("") == default_mark_key()
    assert normalize_mark_key(None) == default_mark_key()
    register_mark("__test_mark_engine_norm__", _draw_test_mark)
    assert normalize_mark_key("__test_mark_engine_norm__") == "__test_mark_engine_norm__"


def test_has_mark():
    register_mark("__test_mark_engine_has__", _draw_test_mark)
    assert has_mark("__test_mark_engine_has__")
    assert not has_mark("__nope__")


def test_mark_pixmap_renders_non_empty():
    register_mark("__test_mark_engine_pixmap__", _draw_test_mark)
    pm = mark_pixmap("__test_mark_engine_pixmap__", 32, "#ff0000")
    assert isinstance(pm, QtGui.QPixmap)
    assert pm.size() == QtCore.QSize(32, 32)
    image = pm.toImage()
    has_color = False
    for x in range(image.width()):
        for y in range(image.height()):
            if QtGui.QColor(image.pixel(x, y)).alpha() > 0:
                has_color = True
                break
        if has_color:
            break
    assert has_color, "registered mark pixmap should have visible pixels"


def test_mark_draw_unknown_key_uses_fallback():
    pm = QtGui.QPixmap(16, 16)
    pm.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pm)
    mark_draw("unknown_key", painter, QtCore.QRectF(0, 0, 16, 16), QtGui.QColor("#00ff00"))
    painter.end()


def test_overflow_badge_runs():
    pm = QtGui.QPixmap(32, 32)
    pm.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pm)
    draw_overflow_badge(painter, QtCore.QRectF(0, 0, 32, 32), 5, QtGui.QColor("#888888"))
    painter.end()
