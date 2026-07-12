from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from ..utils.formatting import dpix
from ..utils.logs import AppLogger


MIN_VISIBLE_TITLE_PX = 256
TITLE_BAND_PX = 24


def screen_geometry_for(pos: QtCore.QPoint, fallback: QtWidgets.QWidget | None = None) -> QtCore.QRect | None:
    screen = QtWidgets.QApplication.screenAt(pos)
    if screen is None and fallback is not None:
        screen = fallback.screen()
    if screen is None:
        screen = QtWidgets.QApplication.primaryScreen()
    return screen.availableGeometry() if screen is not None else None


def clamp_point(pos: QtCore.QPoint, size: QtCore.QSize, geo: QtCore.QRect) -> QtCore.QPoint:
    max_x = geo.left() + max(0, geo.width() - size.width())
    max_y = geo.top() + max(0, geo.height() - size.height())
    return QtCore.QPoint(
        min(max(pos.x(), geo.left()), max_x),
        min(max(pos.y(), geo.top()), max_y),
    )


def _best_screen_geometry(rect: QtCore.QRect) -> QtCore.QRect | None:
    best: QtCore.QRect | None = None
    best_overlap = -1
    for screen in QtWidgets.QApplication.screens():
        geo = screen.availableGeometry()
        inter = geo.intersected(rect)
        overlap = inter.width() * inter.height() if inter.isValid() else 0
        if overlap > best_overlap:
            best_overlap = overlap
            best = geo
    if best is None:
        primary = QtWidgets.QApplication.primaryScreen()
        best = primary.availableGeometry() if primary is not None else None
    return best


def _grab_band_height() -> int:
    return dpix(TITLE_BAND_PX)


def _min_visible() -> int:
    return dpix(MIN_VISIBLE_TITLE_PX)


def _title_band(rect: QtCore.QRect) -> QtCore.QRect:
    return QtCore.QRect(rect.left(), rect.top(), rect.width(), min(rect.height(), _grab_band_height()))


def _title_visible_on_any_screen(rect: QtCore.QRect) -> bool:
    band = _title_band(rect)
    req_w = min(rect.width(), _min_visible())
    req_h = band.height()
    for screen in QtWidgets.QApplication.screens():
        inter = screen.availableGeometry().intersected(band)
        if inter.width() >= req_w and inter.height() >= req_h:
            return True
    return False


def constrain_to_screens(rect: QtCore.QRect) -> QtCore.QRect:
    if _title_visible_on_any_screen(rect):
        return rect

    geo = _best_screen_geometry(rect)
    if geo is None:
        return rect

    visible_w = min(rect.width(), _min_visible())
    visible_h = min(rect.height(), _grab_band_height())

    min_x = geo.left() + visible_w - rect.width()
    max_x = geo.right() + 1 - visible_w
    min_y = geo.top()
    max_y = geo.bottom() + 1 - visible_h

    new_x = min(max(rect.x(), min_x), max_x)
    new_y = min(max(rect.y(), min_y), max_y)
    return QtCore.QRect(new_x, new_y, rect.width(), rect.height())


def keep_window_on_screen(window: QtWidgets.QWidget) -> None:
    if window.isFullScreen() or window.isMaximized():
        return
    frame = window.frameGeometry()
    corrected = constrain_to_screens(frame)
    if corrected.topLeft() == frame.topLeft():
        return
    window.move(corrected.topLeft())
    AppLogger.info(
        f"Window '{window.objectName() or window.windowTitle() or type(window).__name__}' "
        f"was off-screen; repositioned to ({corrected.left()}, {corrected.top()})."
    )
