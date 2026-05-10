from PySide6 import QtCore, QtGui

import pytest

from wafer.core.qt.badge_engine import (
    badge_shape_keys,
    badge_shape_pixmap,
    default_badge_shape_key,
    draw_overflow_badge,
    draw_badge_shape,
    has_badge_shape,
    normalize_badge_shape_key,
    register_badge_shape,
)


@pytest.fixture(autouse=True)
def _ensure_qapp(qtbot):
    pass


def _draw_test_shape(painter: QtGui.QPainter, rect: QtCore.QRectF, color: QtGui.QColor):
    painter.setPen(QtCore.Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawRect(rect)


def test_register_badge_shape_adds_key():
    register_badge_shape("__test_badge_engine_rect__", _draw_test_shape)
    assert "__test_badge_engine_rect__" in badge_shape_keys()
    assert has_badge_shape("__test_badge_engine_rect__")


def test_normalize_badge_shape_key_falls_back_to_registered_default():
    assert normalize_badge_shape_key("nonexistent") == default_badge_shape_key()
    assert normalize_badge_shape_key("") == default_badge_shape_key()
    assert normalize_badge_shape_key(None) == default_badge_shape_key()
    register_badge_shape("__test_badge_engine_norm__", _draw_test_shape)
    assert normalize_badge_shape_key("__test_badge_engine_norm__") == "__test_badge_engine_norm__"


def test_has_badge_shape():
    register_badge_shape("__test_badge_engine_has__", _draw_test_shape)
    assert has_badge_shape("__test_badge_engine_has__")
    assert not has_badge_shape("__nope__")


def test_badge_shape_pixmap_renders_non_empty():
    register_badge_shape("__test_badge_engine_pixmap__", _draw_test_shape)
    pm = badge_shape_pixmap("__test_badge_engine_pixmap__", 32, "#ff0000")
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
    assert has_color, "registered badge shape pixmap should have visible pixels"


def test_draw_badge_shape_unknown_key_uses_fallback():
    pm = QtGui.QPixmap(16, 16)
    pm.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pm)
    draw_badge_shape("unknown_key", painter, QtCore.QRectF(0, 0, 16, 16), QtGui.QColor("#00ff00"))
    painter.end()


def test_overflow_badge_runs():
    pm = QtGui.QPixmap(32, 32)
    pm.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pm)
    draw_overflow_badge(painter, QtCore.QRectF(0, 0, 32, 32), 5, QtGui.QColor("#888888"))
    painter.end()
