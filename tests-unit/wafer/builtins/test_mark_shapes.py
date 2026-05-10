from PySide6 import QtCore, QtGui

from wafer.builtins.mark import shapes
from wafer.core.qt.badge_engine import badge_shape_keys, badge_shape_pixmap, default_badge_shape_key, has_badge_shape


def _alpha_bounds(image: QtGui.QImage) -> QtCore.QRect:
    left = image.width()
    top = image.height()
    right = -1
    bottom = -1
    for x in range(image.width()):
        for y in range(image.height()):
            if QtGui.QColor(image.pixel(x, y)).alpha() <= 0:
                continue
            left = min(left, x)
            top = min(top, y)
            right = max(right, x)
            bottom = max(bottom, y)
    if right < left or bottom < top:
        return QtCore.QRect()
    return QtCore.QRect(left, top, right - left + 1, bottom - top + 1)


def test_builtin_mark_shapes_register_standard_keys(qtbot):
    shapes.register_standard_shapes()
    keys = badge_shape_keys()
    for expected in ("circle", "square", "heart", "star", "triangle_up", "triangle_down", "diamond", "hexagon", "pentagon", "plus_filled", "cross_filled"):
        assert expected in keys
        assert has_badge_shape(expected)
    assert default_badge_shape_key() == shapes.DEFAULT_SHAPE_KEY


def test_builtin_mark_shape_pixmap_renders(qtbot):
    pm = badge_shape_pixmap("heart", 32, "#ff0000")
    assert isinstance(pm, QtGui.QPixmap)
    assert pm.size() == QtCore.QSize(32, 32)
    image = pm.toImage()
    assert any(QtGui.QColor(image.pixel(x, y)).alpha() > 0 for x in range(image.width()) for y in range(image.height()))


def test_builtin_heart_shape_is_centered_in_bounds(qtbot):
    pm = badge_shape_pixmap("heart", 64, "#ff0000")
    image = pm.toImage()
    bounds = _alpha_bounds(image)
    assert not bounds.isNull()
    assert abs(bounds.center().x() - image.rect().center().x()) <= 2
    assert abs(bounds.center().y() - image.rect().center().y()) <= 2
    assert bounds.width() >= 40
    assert bounds.height() >= 40