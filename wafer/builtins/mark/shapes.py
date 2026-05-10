from __future__ import annotations

from functools import cache
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QTransform

from ...core.qt.badge_engine import register_badge_shape


DEFAULT_SHAPE_KEY = "circle"
_DEFAULT_MARK_SCALE = 0.96


def _filled(painter: QPainter, color: QColor) -> None:
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)


def _fit_shape_rect(rect: QRectF, *, scale: float = _DEFAULT_MARK_SCALE, aspect: float = 1.0) -> QRectF:
    outer = QRectF(rect)
    if outer.isNull() or outer.width() <= 0 or outer.height() <= 0:
        return outer
    scale = max(0.0, min(1.0, float(scale)))
    aspect = max(0.001, float(aspect))
    outer_aspect = outer.width() / outer.height()
    if outer_aspect >= aspect:
        height = outer.height() * scale
        width = height * aspect
    else:
        width = outer.width() * scale
        height = width / aspect
    center = outer.center()
    return QRectF(center.x() - width / 2, center.y() - height / 2, width, height)


def _fit_path(path: QPainterPath, rect: QRectF, *, scale: float = _DEFAULT_MARK_SCALE) -> QPainterPath:
    source = path.boundingRect()
    if source.isNull() or source.width() <= 0 or source.height() <= 0:
        return QPainterPath(path)
    target = _fit_shape_rect(rect, scale=scale, aspect=source.width() / source.height())
    transform = QTransform()
    transform.translate(target.center().x(), target.center().y())
    transform.scale(target.width() / source.width(), target.height() / source.height())
    transform.translate(-source.center().x(), -source.center().y())
    return transform.map(path)


@cache
def _heart_path() -> QPainterPath:
    path = QPainterPath()
    samples = 180
    for index in range(samples + 1):
        t = (math.tau * index) / samples
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        point = QPointF(x, -y)
        if index == 0:
            path.moveTo(point)
        else:
            path.lineTo(point)
    path.closeSubpath()
    return path


@cache
def _star_path() -> QPainterPath:
    path = QPainterPath()
    for index in range(10):
        angle = -math.pi / 2 + index * math.pi / 5
        radius = 1.0 if index % 2 == 0 else 0.45
        point = QPointF(radius * math.cos(angle), radius * math.sin(angle))
        if index == 0:
            path.moveTo(point)
        else:
            path.lineTo(point)
    path.closeSubpath()
    return path


@cache
def _regular_polygon_path(sides: int, rotation: float = -math.pi / 2) -> QPainterPath:
    path = QPainterPath()
    for index in range(sides):
        angle = rotation + index * math.tau / sides
        point = QPointF(math.cos(angle), math.sin(angle))
        if index == 0:
            path.moveTo(point)
        else:
            path.lineTo(point)
    path.closeSubpath()
    return path


@cache
def _plus_path() -> QPainterPath:
    path = QPainterPath()
    bar = 0.22
    arm = 1.0
    path.addRect(QRectF(-arm, -bar, arm * 2, bar * 2))
    vertical = QPainterPath()
    vertical.addRect(QRectF(-bar, -arm, bar * 2, arm * 2))
    return path.united(vertical)


@cache
def _cross_path() -> QPainterPath:
    arm = 1.0
    bar = 0.24
    diag1 = QPainterPath()
    diag1.moveTo(QPointF(-arm - bar, -arm + bar))
    diag1.lineTo(QPointF(arm - bar, arm + bar))
    diag1.lineTo(QPointF(arm + bar, arm - bar))
    diag1.lineTo(QPointF(-arm + bar, -arm - bar))
    diag1.closeSubpath()
    diag2 = QPainterPath()
    diag2.moveTo(QPointF(-arm - bar, arm - bar))
    diag2.lineTo(QPointF(arm - bar, -arm - bar))
    diag2.lineTo(QPointF(arm + bar, -arm + bar))
    diag2.lineTo(QPointF(-arm + bar, arm + bar))
    diag2.closeSubpath()
    return diag1.united(diag2)


def _draw_circle(p: QPainter, r: QRectF, color: QColor):
    _filled(p, color)
    p.drawEllipse(_fit_shape_rect(r))


def _draw_square(p: QPainter, r: QRectF, color: QColor):
    _filled(p, color)
    box = _fit_shape_rect(r)
    radius = box.width() * 0.18
    p.drawRoundedRect(box, radius, radius)


def _draw_heart(p: QPainter, r: QRectF, color: QColor):
    _filled(p, color)
    p.drawPath(_fit_path(_heart_path(), r, scale=0.98))


def _draw_star(p: QPainter, r: QRectF, color: QColor):
    _filled(p, color)
    p.drawPath(_fit_path(_star_path(), r))


def _draw_triangle_up(p: QPainter, r: QRectF, color: QColor):
    _filled(p, color)
    p.drawPath(_fit_path(_regular_polygon_path(3, rotation=-math.pi / 2), r))


def _draw_triangle_down(p: QPainter, r: QRectF, color: QColor):
    _filled(p, color)
    p.drawPath(_fit_path(_regular_polygon_path(3, rotation=math.pi / 2), r))


def _draw_diamond(p: QPainter, r: QRectF, color: QColor):
    _filled(p, color)
    p.drawPath(_fit_path(_regular_polygon_path(4, rotation=-math.pi / 2), r))


def _draw_hexagon(p: QPainter, r: QRectF, color: QColor):
    _filled(p, color)
    p.drawPath(_fit_path(_regular_polygon_path(6, rotation=0), r))


def _draw_pentagon(p: QPainter, r: QRectF, color: QColor):
    _filled(p, color)
    p.drawPath(_fit_path(_regular_polygon_path(5), r))


def _draw_plus_filled(p: QPainter, r: QRectF, color: QColor):
    _filled(p, color)
    p.drawPath(_fit_path(_plus_path(), r))


def _draw_cross_filled(p: QPainter, r: QRectF, color: QColor):
    _filled(p, color)
    p.drawPath(_fit_path(_cross_path(), r))


def register_standard_shapes() -> None:
    register_badge_shape("circle", _draw_circle, default=True)
    register_badge_shape("square", _draw_square)
    register_badge_shape("heart", _draw_heart)
    register_badge_shape("star", _draw_star)
    register_badge_shape("triangle_up", _draw_triangle_up)
    register_badge_shape("triangle_down", _draw_triangle_down)
    register_badge_shape("diamond", _draw_diamond)
    register_badge_shape("hexagon", _draw_hexagon)
    register_badge_shape("pentagon", _draw_pentagon)
    register_badge_shape("plus_filled", _draw_plus_filled)
    register_badge_shape("cross_filled", _draw_cross_filled)


register_standard_shapes()
