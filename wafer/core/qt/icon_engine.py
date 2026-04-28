from __future__ import annotations

import math
from collections.abc import Callable

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QIcon,
    QIconEngine,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)

from ..color.theme import ThemeManager

IconDrawFn = Callable[[QPainter, QRectF, QColor], None]

_REGISTRY: dict[str, tuple[IconDrawFn, float]] = {}


def _register(key: str, padding: float = 0.15):
    def decorator(fn: IconDrawFn) -> IconDrawFn:
        _REGISTRY[key] = (fn, padding)
        return fn

    return decorator


class _ThemedIconEngine(QIconEngine):
    def __init__(self, draw_fn: IconDrawFn, padding: float = 0.0, margin: float = 0.0, color: QColor | str | None = None):
        super().__init__()
        self._draw_fn = draw_fn
        self._padding = max(0.0, min(0.5, padding))
        self._margin = max(0.0, min(0.5, margin))
        self._color = QColor(color) if color is not None else None

    def _padded_rect(self, rect: QRectF) -> QRectF:
        r = rect
        if self._margin > 0:
            dx = r.width() * self._margin
            dy = r.height() * self._margin
            r = r.adjusted(dx, dy, -dx, -dy)
        if self._padding > 0:
            dx = r.width() * self._padding
            dy = r.height() * self._padding
            r = r.adjusted(dx, dy, -dx, -dy)
        return r

    def paint(self, painter, rect, mode, state):
        palette = ThemeManager.instance().palette
        color = QColor(self._color) if self._color is not None else QColor(palette.text_primary)
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
        return _ThemedIconEngine(self._draw_fn, self._padding, self._margin, self._color)


def themed_icon(key: str, margin: float = 0.0, color: QColor | str | None = None) -> QIcon:
    entry = _REGISTRY.get(key)
    if entry is None:
        return QIcon()
    fn, padding = entry
    return QIcon(_ThemedIconEngine(fn, padding, margin, color))


def icon_draw(key: str, painter: QPainter, rect: QRectF, color: QColor):
    entry = _REGISTRY.get(key)
    if entry:
        entry[0](painter, rect, color)


@_register("empty")
def _draw_empty(p: QPainter, r: QRectF, color: QColor):
    pass


@_register("gear", padding=0.06)
def _draw_gear(p: QPainter, r: QRectF, color: QColor):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    cx, cy = r.center().x(), r.center().y()
    s = min(r.width(), r.height()) * 0.5
    outer = s * 0.95
    inner = s * 0.60
    hole_r = s * 0.25
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


@_register("gear_small", padding=0.05)
def _draw_gear_small(p: QPainter, r: QRectF, color: QColor):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    cx, cy = r.center().x(), r.center().y()
    s = min(r.width(), r.height()) * 0.4
    outer = s * 0.95
    inner = s * 0.55
    hole_r = s * 0.25
    teeth = 6
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


@_register("folder_plus", padding=0.11)
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
    bw = s * 0.09
    bh = s * 0.25
    cy = (top + r.bottom()) / 2
    cx = r.center().x()
    cross_h = QPainterPath()
    cross_h.addRect(QRectF(cx - bh, cy - bw, bh * 2, bw * 2))
    cross_v = QPainterPath()
    cross_v.addRect(QRectF(cx - bw, cy - bh, bw * 2, bh * 2))
    p.drawPath(body.subtracted(cross_h.united(cross_v)))


@_register("subfolder")
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


@_register("fullscreen", padding=0.18)
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


@_register("window", padding=0.1)
def _draw_window(p: QPainter, r: QRectF, color: QColor):
    lw = max(1.5, min(r.width(), r.height()) * 0.10)
    pen = QPen(color, lw)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    m = lw / 2
    ir = r.adjusted(m, m, -m, -m)
    title_h = ir.height() * 0.28
    p.drawRect(ir)
    p.drawLine(QPointF(ir.left(), ir.top() + title_h), QPointF(ir.right(), ir.top() + title_h))
    btn_w = ir.width() * 0.22
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    p.drawRect(QRectF(ir.right() - btn_w, ir.top(), btn_w, title_h))


@_register("plus", padding=0.14)
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


@_register("minus")
def _draw_minus(p: QPainter, r: QRectF, color: QColor):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    s = min(r.width(), r.height())
    bw = s * 0.10
    arm = s * 0.38
    cy = r.center().y()
    cx = r.center().x()
    p.drawRect(QRectF(cx - arm, cy - bw, arm * 2, bw * 2))


@_register("play")
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


@_register("pause")
def _draw_pause(p: QPainter, r: QRectF, color: QColor):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    w = r.width() * 0.3
    p.drawRect(QRectF(r.left(), r.top(), w, r.height()))
    p.drawRect(QRectF(r.right() - w, r.top(), w, r.height()))


@_register("volume")
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


@_register("muted")
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


@_register("cross", padding=0.2)
def _draw_cross(p: QPainter, r: QRectF, color: QColor):
    lw = max(1.5, min(r.width(), r.height()) * 0.17)
    pen = QPen(color, lw)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    m = min(r.width(), r.height()) * 0.15
    p.drawLine(QPointF(r.left() + m, r.top() + m), QPointF(r.right() - m, r.bottom() - m))
    p.drawLine(QPointF(r.right() - m, r.top() + m), QPointF(r.left() + m, r.bottom() - m))


@_register("check", padding=0.18)
def _draw_check(p: QPainter, r: QRectF, color: QColor):
    lw = max(1.5, min(r.width(), r.height()) * 0.18)
    pen = QPen(color, lw)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    x0, y0 = r.left(), r.top()
    w, h = r.width(), r.height()
    path = QPainterPath()
    path.moveTo(QPointF(x0 + w * 0.15, y0 + h * 0.50))
    path.lineTo(QPointF(x0 + w * 0.40, y0 + h * 0.78))
    path.lineTo(QPointF(x0 + w * 0.85, y0 + h * 0.22))
    p.drawPath(path)


@_register("checkbox_unchecked", padding=0.13)
def _draw_checkbox_unchecked(p: QPainter, r: QRectF, color: QColor):
    lw = max(1.2, min(r.width(), r.height()) * 0.13)
    pen = QPen(color, lw)
    pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    inset = lw / 2
    box = r.adjusted(inset, inset, -inset, -inset)
    radius = min(box.width(), box.height()) * 0.15
    p.drawRoundedRect(box, radius, radius)


@_register("checkbox_checked", padding=0.13)
def _draw_checkbox_checked(p: QPainter, r: QRectF, color: QColor):
    lw = max(1.2, min(r.width(), r.height()) * 0.13)
    pen = QPen(color, lw)
    pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    inset = lw / 2
    box = r.adjusted(inset, inset, -inset, -inset)
    radius = min(box.width(), box.height()) * 0.15
    p.drawRoundedRect(box, radius, radius)
    check_pen = QPen(color, lw * 1.05)
    check_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    check_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(check_pen)
    x0, y0 = r.left(), r.top()
    w, h = r.width(), r.height()
    path = QPainterPath()
    path.moveTo(QPointF(x0 + w * 0.22, y0 + h * 0.52))
    path.lineTo(QPointF(x0 + w * 0.43, y0 + h * 0.74))
    path.lineTo(QPointF(x0 + w * 0.80, y0 + h * 0.28))
    p.drawPath(path)


@_register("chevron_down", padding=0.15)
def _draw_chevron_down(p: QPainter, r: QRectF, color: QColor):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    oy = r.height() * 0.15
    path = QPainterPath()
    path.moveTo(QPointF(r.left(), r.top() + oy))
    path.lineTo(QPointF(r.right(), r.top() + oy))
    path.lineTo(QPointF(r.center().x(), r.bottom() - oy))
    path.closeSubpath()
    p.drawPath(path)


@_register("chevron_right", padding=0.15)
def _draw_chevron_right(p: QPainter, r: QRectF, color: QColor):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    ox = r.width() * 0.15
    path = QPainterPath()
    path.moveTo(QPointF(r.left() + ox, r.top()))
    path.lineTo(QPointF(r.left() + ox, r.bottom()))
    path.lineTo(QPointF(r.right() - ox, r.center().y()))
    path.closeSubpath()
    p.drawPath(path)


@_register("sort", padding=0.09)
def _draw_sort(p: QPainter, r: QRectF, color: QColor):
    lw = max(1.5, min(r.width(), r.height()) * 0.10)
    pen = QPen(color, lw)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    gap = min(r.width(), r.height()) * 0.20
    head = min(r.width(), r.height()) * 0.16
    top = r.top() + r.height() * 0.16
    bot = r.bottom() - r.height() * 0.16
    lx = r.center().x() - gap
    rx = r.center().x() + gap
    p.drawLine(QPointF(lx, bot), QPointF(lx, top))
    p.drawLine(QPointF(lx, top), QPointF(lx - head, top + head))
    p.drawLine(QPointF(lx, top), QPointF(lx + head, top + head))
    p.drawLine(QPointF(rx, top), QPointF(rx, bot))
    p.drawLine(QPointF(rx, bot), QPointF(rx - head, bot - head))
    p.drawLine(QPointF(rx, bot), QPointF(rx + head, bot - head))


@_register("menu", padding=0.15)
def _draw_menu(p: QPainter, r: QRectF, color: QColor):
    lw = max(1.5, min(r.width(), r.height()) * 0.11)
    pen = QPen(color, lw)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    cy = r.center().y()
    gap = r.height() * 0.25
    mx = r.left() + r.width() * 0.1
    mx2 = r.right() - r.width() * 0.1
    p.drawLine(QPointF(mx, cy - gap), QPointF(mx2, cy - gap))
    p.drawLine(QPointF(mx, cy), QPointF(mx2, cy))
    p.drawLine(QPointF(mx, cy + gap), QPointF(mx2, cy + gap))


@_register("layout_edit", padding=0.12)
def _draw_layout_edit(p: QPainter, r: QRectF, color: QColor):
    lw = max(1.5, min(r.width(), r.height()) * 0.10)
    pen = QPen(color, lw)
    pen.setCapStyle(Qt.PenCapStyle.SquareCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    m = lw / 2
    ir = r.adjusted(m, m, -m, -m)
    p.drawRect(ir)
    vx = ir.left() + ir.width() * 0.35
    p.drawLine(QPointF(vx, ir.top()), QPointF(vx, ir.bottom()))
    hy = ir.top() + ir.height() * 0.5
    p.drawLine(QPointF(vx, hy), QPointF(ir.right(), hy))


@_register("refresh", padding=0.12)
def _draw_refresh(p: QPainter, r: QRectF, color: QColor):
    lw = max(1.5, min(r.width(), r.height()) * 0.12)
    pen = QPen(color, lw)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    cx, cy = r.center().x(), r.center().y()
    rad = min(r.width(), r.height()) * 0.38
    arc_rect = QRectF(cx - rad, cy - rad, rad * 2, rad * 2)
    p.drawArc(arc_rect, 60 * 16, 300 * 16)
    arrow_angle = 60 * math.pi / 180
    tip = QPointF(cx + rad * math.cos(arrow_angle), cy - rad * math.sin(arrow_angle))
    al = rad * 0.4
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    arrow = QPainterPath()
    arrow.moveTo(tip)
    arrow.lineTo(tip.x() + al * 0.3, tip.y() + al)
    arrow.lineTo(tip.x() - al * 0.7, tip.y() + al * 0.3)
    arrow.closeSubpath()
    p.drawPath(arrow)


@_register("history", padding=0.10)
def _draw_history(p: QPainter, r: QRectF, color: QColor):
    s = min(r.width(), r.height())
    lw = max(1.4, s * 0.10)
    pen = QPen(color, lw)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    cx, cy = r.center().x(), r.center().y()
    rad = s * 0.38
    arc_rect = QRectF(cx - rad, cy - rad, rad * 2, rad * 2)
    p.drawArc(arc_rect, 35 * 16, 285 * 16)

    arrow_angle = 215 * math.pi / 180
    tip = QPointF(cx + rad * math.cos(arrow_angle), cy + rad * math.sin(arrow_angle))
    al = s * 0.18
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    arrow = QPainterPath()
    arrow.moveTo(tip)
    arrow.lineTo(QPointF(tip.x() + al * 0.95, tip.y() - al * 0.10))
    arrow.lineTo(QPointF(tip.x() + al * 0.20, tip.y() - al * 0.90))
    arrow.closeSubpath()
    p.drawPath(arrow)

    pen.setWidthF(max(1.2, s * 0.08))
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawLine(QPointF(cx, cy), QPointF(cx, cy - s * 0.20))
    p.drawLine(QPointF(cx, cy), QPointF(cx + s * 0.17, cy + s * 0.10))


@_register("save", padding=0.12)
def _draw_save(p: QPainter, r: QRectF, color: QColor):
    s = min(r.width(), r.height())
    lw = max(1.3, s * 0.09)
    pen = QPen(color, lw)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    body = r.adjusted(lw / 2, lw / 2, -lw / 2, -lw / 2)
    notch = s * 0.18
    path = QPainterPath()
    path.moveTo(body.left(), body.top())
    path.lineTo(body.right() - notch, body.top())
    path.lineTo(body.right(), body.top() + notch)
    path.lineTo(body.right(), body.bottom())
    path.lineTo(body.left(), body.bottom())
    path.closeSubpath()
    p.drawPath(path)

    top = QRectF(body.left() + s * 0.15, body.top(), body.width() * 0.50, body.height() * 0.33)
    p.drawRect(top)
    label = QRectF(body.left() + s * 0.18, body.top() + body.height() * 0.58, body.width() * 0.64, body.height() * 0.26)
    p.drawRoundedRect(label, s * 0.03, s * 0.03)


@_register("star", padding=0.10)
def _draw_star(p: QPainter, r: QRectF, color: QColor):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    cx, cy = r.center().x(), r.center().y()
    s = min(r.width(), r.height()) * 0.48
    path = QPainterPath()
    for i in range(10):
        angle = math.pi / 2 + 2 * math.pi * i / 10
        rad = s if i % 2 == 0 else s * 0.42
        pt = QPointF(cx + rad * math.cos(angle), cy - rad * math.sin(angle))
        if i == 0:
            path.moveTo(pt)
        else:
            path.lineTo(pt)
    path.closeSubpath()
    p.drawPath(path)


@_register("warning_triangle", padding=0.08)
def _draw_warning_triangle(p: QPainter, r: QRectF, color: QColor):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    cx = r.center().x()
    path = QPainterPath()
    path.moveTo(QPointF(cx, r.top()))
    path.lineTo(QPointF(r.right(), r.bottom()))
    path.lineTo(QPointF(r.left(), r.bottom()))
    path.closeSubpath()
    s = min(r.width(), r.height())
    bar_w = s * 0.09
    dot_r = s * 0.07
    excl_top = r.top() + s * 0.38
    excl_bot = r.bottom() - s * 0.30
    dot_cy = r.bottom() - s * 0.18
    excl = QPainterPath()
    excl.addRect(QRectF(cx - bar_w, excl_top, bar_w * 2, excl_bot - excl_top))
    excl.addEllipse(QPointF(cx, dot_cy), dot_r, dot_r)
    p.drawPath(path.subtracted(excl))


@_register("external_link", padding=0.12)
def _draw_external_link(p: QPainter, r: QRectF, color: QColor):
    lw = max(1.5, min(r.width(), r.height()) * 0.11)
    pen = QPen(color, lw)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    m = lw / 2
    ir = r.adjusted(m, m, -m, -m)
    w, h = ir.width(), ir.height()
    gap = w * 0.35
    box = QRectF(ir.left(), ir.top() + gap * 0.5, w - gap * 0.5, h - gap * 0.5)
    path = QPainterPath()
    path.moveTo(box.left() + gap * 0.6, box.top())
    path.lineTo(box.left(), box.top())
    path.lineTo(box.left(), box.bottom())
    path.lineTo(box.right(), box.bottom())
    path.lineTo(box.right(), box.bottom() - gap * 0.6)
    p.drawPath(path)
    ax = ir.right()
    ay = ir.top()
    p.drawLine(QPointF(ir.center().x(), ir.center().y()), QPointF(ax, ay))
    arm = w * 0.25
    p.drawLine(QPointF(ax - arm, ay), QPointF(ax, ay))
    p.drawLine(QPointF(ax, ay), QPointF(ax, ay + arm))


def _draw_lock_body(p: QPainter, r: QRectF, color: QColor, shackle_x_offset: float):
    lw = max(1.2, min(r.width(), r.height()) * 0.10)
    pen = QPen(color, lw)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(color)
    w, h = r.width(), r.height()
    body = QRectF(r.left() + w * 0.15, r.top() + h * 0.45, w * 0.70, h * 0.50)
    p.drawRoundedRect(body, w * 0.08, w * 0.08)
    p.setBrush(Qt.BrushStyle.NoBrush)
    shackle_w = w * 0.50
    shackle = QRectF(r.left() + (w - shackle_w) / 2 + shackle_x_offset, r.top() + h * 0.10, shackle_w, h * 0.45)
    path = QPainterPath()
    path.arcMoveTo(shackle, 0)
    path.arcTo(shackle, 0, 180)
    p.drawPath(path)


@_register("lock", padding=0.10)
def _draw_lock(p: QPainter, r: QRectF, color: QColor):
    _draw_lock_body(p, r, color, 0.0)


@_register("lock_open", padding=0.10)
def _draw_lock_open(p: QPainter, r: QRectF, color: QColor):
    _draw_lock_body(p, r, color, r.width() * 0.30)


@_register("pencil", padding=0.17)
def _draw_pencil(p: QPainter, r: QRectF, color: QColor):
    lw = max(1.2, min(r.width(), r.height()) * 0.09)
    pen = QPen(color, lw)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(color)
    s = min(r.width(), r.height())
    cx, cy = r.center().x(), r.center().y()
    half = s * 0.45
    tip = QPointF(cx - half, cy + half)
    tail = QPointF(cx + half, cy - half)
    body_w = s * 0.18
    dx = tail.x() - tip.x()
    dy = tail.y() - tip.y()
    length = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / length, dx / length
    head_len = s * 0.20
    tip_in = QPointF(tip.x() + dx / length * head_len, tip.y() + dy / length * head_len)
    body = QPainterPath()
    body.moveTo(QPointF(tip_in.x() + nx * body_w, tip_in.y() + ny * body_w))
    body.lineTo(QPointF(tail.x() + nx * body_w, tail.y() + ny * body_w))
    body.lineTo(QPointF(tail.x() - nx * body_w, tail.y() - ny * body_w))
    body.lineTo(QPointF(tip_in.x() - nx * body_w, tip_in.y() - ny * body_w))
    body.closeSubpath()
    p.drawPath(body)
    head = QPainterPath()
    head.moveTo(tip)
    head.lineTo(QPointF(tip_in.x() + nx * body_w, tip_in.y() + ny * body_w))
    head.lineTo(QPointF(tip_in.x() - nx * body_w, tip_in.y() - ny * body_w))
    head.closeSubpath()
    p.drawPath(head)


@_register("trash", padding=0.10)
def _draw_trash(p: QPainter, r: QRectF, color: QColor):
    lw = max(1.2, min(r.width(), r.height()) * 0.09)
    pen = QPen(color, lw)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    w, h = r.width(), r.height()
    cx = r.center().x()
    lid_y = r.top() + h * 0.22
    p.drawLine(QPointF(r.left() + w * 0.10, lid_y), QPointF(r.right() - w * 0.10, lid_y))
    handle_w = w * 0.22
    handle_y = r.top() + h * 0.10
    p.drawLine(QPointF(cx - handle_w, handle_y), QPointF(cx + handle_w, handle_y))
    p.drawLine(QPointF(cx - handle_w, handle_y), QPointF(cx - handle_w, lid_y))
    p.drawLine(QPointF(cx + handle_w, handle_y), QPointF(cx + handle_w, lid_y))
    body_left = r.left() + w * 0.20
    body_right = r.right() - w * 0.20
    body_bottom = r.bottom() - h * 0.05
    p.drawLine(QPointF(body_left, lid_y), QPointF(body_left + w * 0.05, body_bottom))
    p.drawLine(QPointF(body_right, lid_y), QPointF(body_right - w * 0.05, body_bottom))
    p.drawLine(QPointF(body_left + w * 0.05, body_bottom), QPointF(body_right - w * 0.05, body_bottom))
    bar_y_top = lid_y + h * 0.15
    bar_y_bot = body_bottom - h * 0.10
    p.drawLine(QPointF(cx - w * 0.10, bar_y_top), QPointF(cx - w * 0.10, bar_y_bot))
    p.drawLine(QPointF(cx + w * 0.10, bar_y_top), QPointF(cx + w * 0.10, bar_y_bot))
