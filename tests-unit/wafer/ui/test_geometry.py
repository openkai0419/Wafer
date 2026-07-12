from PySide6 import QtCore, QtWidgets

from wafer.ui.geometry import (
    TITLE_BAND_PX,
    clamp_point,
    constrain_to_screens,
    keep_window_on_screen,
    screen_geometry_for,
)


def _primary_geo():
    return QtWidgets.QApplication.primaryScreen().availableGeometry()


def _all_geos():
    return [s.availableGeometry() for s in QtWidgets.QApplication.screens()]


def _far_offscreen_point():
    geos = _all_geos()
    right = max(g.right() for g in geos)
    bottom = max(g.bottom() for g in geos)
    return QtCore.QPoint(right + 5000, bottom + 5000)


def _grab_visible_on_any_screen(rect):
    band = QtCore.QRect(rect.left(), rect.top(), rect.width(), min(TITLE_BAND_PX, rect.height()))
    for g in _all_geos():
        inter = g.intersected(band)
        if inter.isValid() and inter.top() == band.top() and inter.width() > 0 and inter.height() == band.height():
            return True
    return False


def test_screen_geometry_for_returns_available(qtbot):
    geo = _primary_geo()
    result = screen_geometry_for(geo.center())
    assert result is not None
    assert result.contains(geo.center())


def test_clamp_point_pushes_inside(qtbot):
    geo = _primary_geo()
    size = QtCore.QSize(100, 100)
    far = QtCore.QPoint(geo.right() + 500, geo.bottom() + 500)
    clamped = clamp_point(far, size, geo)
    assert geo.contains(QtCore.QRect(clamped, size))


def test_constrain_keeps_on_screen_rect_unchanged(qtbot):
    geo = _primary_geo()
    rect = QtCore.QRect(geo.left() + 50, geo.top() + 50, 300, 200)
    assert constrain_to_screens(rect) == rect


def test_constrain_keeps_sufficient_title_visible(qtbot):
    rightmost = max(_all_geos(), key=lambda g: g.right())
    rect = QtCore.QRect(rightmost.right() - 150, rightmost.top() + 100, 300, 200)
    assert constrain_to_screens(rect) == rect


def test_constrain_repositions_when_title_sliver_only(qtbot):
    rightmost = max(_all_geos(), key=lambda g: g.right())
    rect = QtCore.QRect(rightmost.right() - 5, rightmost.top() + 100, 300, 200)
    result = constrain_to_screens(rect)
    assert result != rect
    assert _grab_visible_on_any_screen(result)


def test_constrain_keeps_narrow_window_when_fully_visible(qtbot):
    rightmost = max(_all_geos(), key=lambda g: g.right())
    width = 20
    rect = QtCore.QRect(rightmost.right() + 1 - width, rightmost.top() + 100, width, 200)
    assert constrain_to_screens(rect) == rect


def test_constrain_repositions_narrow_window_when_partially_visible(qtbot):
    rightmost = max(_all_geos(), key=lambda g: g.right())
    width = 20
    visible = 5
    rect = QtCore.QRect(rightmost.right() + 1 - visible, rightmost.top() + 100, width, 200)
    result = constrain_to_screens(rect)
    assert result != rect
    assert _grab_visible_on_any_screen(result)


def test_constrain_repositions_when_title_above_screen(qtbot):
    geo = _primary_geo()
    rect = QtCore.QRect(geo.left() + 100, geo.top() - 100, 300, 200)
    result = constrain_to_screens(rect)
    assert result != rect
    assert _grab_visible_on_any_screen(result)


def test_constrain_moves_offscreen_rect_back(qtbot):
    origin = _far_offscreen_point()
    rect = QtCore.QRect(origin.x(), origin.y(), 300, 200)
    result = constrain_to_screens(rect)
    assert result.size() == rect.size()
    assert _grab_visible_on_any_screen(result)


def test_constrain_negative_offscreen_rect_back(qtbot):
    geos = _all_geos()
    left = min(g.left() for g in geos)
    top = min(g.top() for g in geos)
    rect = QtCore.QRect(left - 3000, top - 3000, 300, 200)
    result = constrain_to_screens(rect)
    assert result.size() == rect.size()
    assert _grab_visible_on_any_screen(result)


def test_constrain_oversized_window_keeps_top_left_visible(qtbot):
    geo = _primary_geo()
    rect = QtCore.QRect(geo.left() - 500, geo.top() - 500, geo.width() + 2000, geo.height() + 2000)
    result = constrain_to_screens(rect)
    assert result.size() == rect.size()
    assert _grab_visible_on_any_screen(result)


def test_keep_window_on_screen_repositions_offscreen(qtbot):
    origin = _far_offscreen_point()
    w = QtWidgets.QWidget()
    qtbot.addWidget(w)
    w.resize(300, 200)
    w.show()
    qtbot.waitExposed(w)
    w.move(origin)
    keep_window_on_screen(w)
    assert _grab_visible_on_any_screen(w.frameGeometry())


def test_keep_window_on_screen_leaves_visible_window(qtbot):
    geo = _primary_geo()
    w = QtWidgets.QWidget()
    qtbot.addWidget(w)
    w.resize(300, 200)
    w.show()
    qtbot.waitExposed(w)
    w.move(geo.left() + 100, geo.top() + 100)
    before = w.frameGeometry().topLeft()
    keep_window_on_screen(w)
    assert w.frameGeometry().topLeft() == before
