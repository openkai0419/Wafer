from __future__ import annotations

import math
from typing import Callable

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import (
    QColor, QIcon, QIconEngine, QPainter, QPainterPath, QPen, QPixmap,
)

from ..color.theme import ThemeManager

IconDrawFn = Callable[[QPainter, QRectF, QColor], None]

_REGISTRY: dict[str, IconDrawFn] = {}


def _register(key: str):
    def decorator(fn: IconDrawFn) -> IconDrawFn:
        _REGISTRY[key] = fn
        return fn
    return decorator


class _ThemedIconEngine(QIconEngine):

    def __init__(self, draw_fn: IconDrawFn, padding: float = 0.0):
        super().__init__()
        self._draw_fn = draw_fn
        self._padding = max(0.0, min(0.5, padding))

    def _padded_rect(self, rect: QRectF) -> QRectF:
        if self._padding <= 0:
            return rect
        dx = rect.width() * self._padding
        dy = rect.height() * self._padding
        return rect.adjusted(dx, dy, -dx, -dy)

    def paint(self, painter, rect, mode, state):
        palette = ThemeManager.instance().palette
        color = QColor(palette.text_primary)
        if mode == QIcon.Mode.Disabled:
            color.setAlpha(80)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._draw_fn(painter, self._padded_rect(QRectF(rect)), color)
        painter.restore()

    def pixmap(self, size, mode, state):
        pm = QPixmap(size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        self.paint(p, QRect(QPoint(0, 0), size), mode, state)
        p.end()
        return pm

    def clone(self):
        return _ThemedIconEngine(self._draw_fn, self._padding)


def themed_icon(key: str, padding: float = 0.15) -> QIcon:
    fn = _REGISTRY.get(key)
    if fn is None:
        return QIcon()
    return QIcon(_ThemedIconEngine(fn, padding))


def icon_draw(key: str, painter: QPainter, rect: QRectF, color: QColor):
    fn = _REGISTRY.get(key)
    if fn:
        fn(painter, rect, color)


@_register('gear')
def _draw_gear(p: QPainter, r: QRectF, color: QColor):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    cx, cy = r.center().x(), r.center().y()
    s = min(r.width(), r.height()) * 0.5
    outer = s * 0.95
    inner = s * 0.60
    hole_r = s * 0.22
    teeth = 8
    n = teeth * 4
    path = QPainterPath()
    for i in range(n):
        angle = 2 * math.pi * i / n - math.pi / 2
        phase = i % 4
        rad = inner if phase == 0 or phase == 3 else outer
        pt = QPointF(cx + rad * math.cos(angle), cy + rad * math.sin(angle))
        if i == 0:
            path.moveTo(pt)
        else:
            path.lineTo(pt)
    path.closeSubpath()
    hole = QPainterPath()
    hole.addEllipse(QPointF(cx, cy), hole_r, hole_r)
    p.drawPath(path.subtracted(hole))


@_register('folder_plus')
def _draw_folder_plus(p: QPainter, r: QRectF, color: QColor):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    tab_w = r.width() * 0.35
    tab_h = r.height() * 0.18
    top = r.top() + tab_h
    body = QPainterPath()
    body.moveTo(r.left(), top)
    body.lineTo(r.left(), r.top())
    body.lineTo(r.left() + tab_w, r.top())
    body.lineTo(r.left() + tab_w + tab_h, top)
    body.lineTo(r.right(), top)
    body.lineTo(r.right(), r.bottom())
    body.lineTo(r.left(), r.bottom())
    body.closeSubpath()
    s = min(r.width(), r.height())
    bw = s * 0.08
    bh = s * 0.25
    cy = (top + r.bottom()) / 2
    cx = r.center().x()
    cross_h = QPainterPath()
    cross_h.addRect(QRectF(cx - bh, cy - bw, bh * 2, bw * 2))
    cross_v = QPainterPath()
    cross_v.addRect(QRectF(cx - bw, cy - bh, bw * 2, bh * 2))
    p.drawPath(body.subtracted(cross_h.united(cross_v)))


@_register('subfolder')
def _draw_subfolder(p: QPainter, r: QRectF, color: QColor):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    fw = r.width() * 0.75
    fh = r.height() * 0.55
    tab_w = fw * 0.35
    tab_h = fh * 0.22
    x0, y0 = r.left(), r.top()
    t0 = y0 + tab_h
    back = QPainterPath()
    back.moveTo(x0, t0)
    back.lineTo(x0, y0)
    back.lineTo(x0 + tab_w, y0)
    back.lineTo(x0 + tab_w + tab_h, t0)
    back.lineTo(x0 + fw, t0)
    back.lineTo(x0 + fw, y0 + fh)
    back.lineTo(x0, y0 + fh)
    back.closeSubpath()
    p.drawPath(back)
    ox = r.width() * 0.25
    oy = r.height() * 0.45
    x1, y1 = r.left() + ox, r.top() + oy
    t1 = y1 + tab_h
    front = QPainterPath()
    front.moveTo(x1, t1)
    front.lineTo(x1, y1)
    front.lineTo(x1 + tab_w, y1)
    front.lineTo(x1 + tab_w + tab_h, t1)
    front.lineTo(x1 + fw, t1)
    front.lineTo(x1 + fw, y1 + fh)
    front.lineTo(x1, y1 + fh)
    front.closeSubpath()
    p.drawPath(front)


@_register('fullscreen')
def _draw_fullscreen(p: QPainter, r: QRectF, color: QColor):
    lw = max(1.5, min(r.width(), r.height()) * 0.12)
    pen = QPen(color, lw)
    pen.setCapStyle(Qt.PenCapStyle.SquareCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    m = lw / 2
    ir = r.adjusted(m, m, -m, -m)
    arm = min(ir.width(), ir.height()) * 0.35
    p.drawLine(QPointF(ir.left(), ir.top() + arm), QPointF(ir.left(), ir.top()))
    p.drawLine(QPointF(ir.left(), ir.top()), QPointF(ir.left() + arm, ir.top()))
    p.drawLine(QPointF(ir.right() - arm, ir.top()), QPointF(ir.right(), ir.top()))
    p.drawLine(QPointF(ir.right(), ir.top()), QPointF(ir.right(), ir.top() + arm))
    p.drawLine(QPointF(ir.left(), ir.bottom() - arm), QPointF(ir.left(), ir.bottom()))
    p.drawLine(QPointF(ir.left(), ir.bottom()), QPointF(ir.left() + arm, ir.bottom()))
    p.drawLine(QPointF(ir.right() - arm, ir.bottom()), QPointF(ir.right(), ir.bottom()))
    p.drawLine(QPointF(ir.right(), ir.bottom()), QPointF(ir.right(), ir.bottom() - arm))


@_register('plus')
def _draw_plus(p: QPainter, r: QRectF, color: QColor):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    s = min(r.width(), r.height())
    bw = s * 0.10
    arm = s * 0.38
    cx, cy = r.center().x(), r.center().y()
    h_bar = QPainterPath()
    h_bar.addRect(QRectF(cx - arm, cy - bw, arm * 2, bw * 2))
    v_bar = QPainterPath()
    v_bar.addRect(QRectF(cx - bw, cy - arm, bw * 2, arm * 2))
    p.drawPath(h_bar.united(v_bar))


@_register('minus')
def _draw_minus(p: QPainter, r: QRectF, color: QColor):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    s = min(r.width(), r.height())
    bw = s * 0.10
    arm = s * 0.38
    cy = r.center().y()
    cx = r.center().x()
    p.drawRect(QRectF(cx - arm, cy - bw, arm * 2, bw * 2))


@_register('play')
def _draw_play(p: QPainter, r: QRectF, color: QColor):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    ox = r.width() * 0.2
    path = QPainterPath()
    path.moveTo(QPointF(r.left() + ox, r.top()))
    path.lineTo(QPointF(r.right(), r.center().y()))
    path.lineTo(QPointF(r.left() + ox, r.bottom()))
    path.closeSubpath()
    p.drawPath(path)


@_register('pause')
def _draw_pause(p: QPainter, r: QRectF, color: QColor):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    w = r.width() * 0.3
    p.drawRect(QRectF(r.left(), r.top(), w, r.height()))
    p.drawRect(QRectF(r.right() - w, r.top(), w, r.height()))


@_register('volume')
def _draw_volume(p: QPainter, r: QRectF, color: QColor):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    sw = r.width() * 0.35
    sh = r.height() * 0.5
    sy = r.center().y() - sh / 2
    p.drawRect(QRectF(r.left(), sy, sw, sh))
    path = QPainterPath()
    path.moveTo(QPointF(r.left() + sw, sy))
    path.lineTo(QPointF(r.center().x() + sw * 0.3, r.top()))
    path.lineTo(QPointF(r.center().x() + sw * 0.3, r.bottom()))
    path.lineTo(QPointF(r.left() + sw, sy + sh))
    path.closeSubpath()
    p.drawPath(path)
    p.setBrush(Qt.BrushStyle.NoBrush)
    pen = QPen(color, min(r.width(), r.height()) * 0.1)
    p.setPen(pen)
    cx = r.center().x() + sw * 0.5
    for rad in [r.height() * 0.25, r.height() * 0.4]:
        arc_r = QRectF(cx - rad, r.center().y() - rad, rad * 2, rad * 2)
        p.drawArc(arc_r, -45 * 16, 90 * 16)


@_register('muted')
def _draw_muted(p: QPainter, r: QRectF, color: QColor):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    sw = r.width() * 0.35
    sh = r.height() * 0.5
    sy = r.center().y() - sh / 2
    p.drawRect(QRectF(r.left(), sy, sw, sh))
    path = QPainterPath()
    path.moveTo(QPointF(r.left() + sw, sy))
    path.lineTo(QPointF(r.center().x() + sw * 0.3, r.top()))
    path.lineTo(QPointF(r.center().x() + sw * 0.3, r.bottom()))
    path.lineTo(QPointF(r.left() + sw, sy + sh))
    path.closeSubpath()
    p.drawPath(path)
    error_color = QColor(ThemeManager.instance().palette.error)
    pen = QPen(error_color, min(r.width(), r.height()) * 0.12)
    p.setPen(pen)
    s = min(r.width(), r.height())
    x1 = r.right() - r.width() * 0.2
    d = s * 0.15
    cy = r.center().y()
    p.drawLine(QPointF(x1 - d, cy - d), QPointF(x1 + d, cy + d))
    p.drawLine(QPointF(x1 + d, cy - d), QPointF(x1 - d, cy + d))


@_register('cross')
def _draw_cross(p: QPainter, r: QRectF, color: QColor):
    lw = max(1.5, min(r.width(), r.height()) * 0.14)
    pen = QPen(color, lw)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    m = min(r.width(), r.height()) * 0.15
    p.drawLine(QPointF(r.left() + m, r.top() + m), QPointF(r.right() - m, r.bottom() - m))
    p.drawLine(QPointF(r.right() - m, r.top() + m), QPointF(r.left() + m, r.bottom() - m))


@_register('sort')
def _draw_sort(p: QPainter, r: QRectF, color: QColor):
    lw = max(1.5, min(r.width(), r.height()) * 0.12)
    pen = QPen(color, lw)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    cx = r.center().x()
    head = min(r.width(), r.height()) * 0.22
    top = r.top() + r.height() * 0.12
    bot = r.bottom() - r.height() * 0.12
    p.drawLine(QPointF(cx, top), QPointF(cx - head, top + head))
    p.drawLine(QPointF(cx, top), QPointF(cx + head, top + head))
    p.drawLine(QPointF(cx, top), QPointF(cx, bot))
    p.drawLine(QPointF(cx, bot), QPointF(cx - head, bot - head))
    p.drawLine(QPointF(cx, bot), QPointF(cx + head, bot - head))
