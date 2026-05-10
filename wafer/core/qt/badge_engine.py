from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap


BadgeShapeDrawFn = Callable[[QPainter, QRectF, QColor], None]

_REGISTRY: dict[str, BadgeShapeDrawFn] = {}
_DEFAULT_KEY: str | None = None


def register_badge_shape(key: str, draw: BadgeShapeDrawFn, *, default: bool = False) -> str:
    global _DEFAULT_KEY
    key = str(key or "").strip()
    if not key:
        raise ValueError("badge shape key must not be empty")
    if not callable(draw):
        raise TypeError("badge shape draw function must be callable")
    _REGISTRY[key] = draw
    if default or _DEFAULT_KEY is None:
        _DEFAULT_KEY = key
    return key


def default_badge_shape_key() -> str:
    return _DEFAULT_KEY or ""


def badge_shape_keys() -> list[str]:
    return list(_REGISTRY.keys())


def has_badge_shape(key: str) -> bool:
    return str(key) in _REGISTRY


def normalize_badge_shape_key(key: str | None) -> str:
    text = str(key or "").strip()
    return text if text in _REGISTRY else default_badge_shape_key()


def draw_badge_shape(key: str, painter: QPainter, rect: QRectF, color: QColor) -> None:
    fn = _REGISTRY.get(normalize_badge_shape_key(key))
    if fn is None:
        return
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    fn(painter, rect, color)
    painter.restore()


def badge_shape_pixmap(key: str, size: int, color: QColor | str) -> QPixmap:
    size = max(1, int(size))
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    draw_badge_shape(key, painter, QRectF(0, 0, size, size), QColor(color))
    painter.end()
    return pm


def draw_overflow_badge(p: QPainter, rect: QRectF, count: int, color: QColor) -> None:
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    bg = QColor(color)
    bg.setAlpha(220)
    p.setPen(QPen(QColor(0, 0, 0, 180), max(1.0, min(rect.width(), rect.height()) * 0.06)))
    p.setBrush(bg)
    p.drawEllipse(rect)
    text_color = QColor(Qt.GlobalColor.white) if bg.lightnessF() < 0.55 else QColor(Qt.GlobalColor.black)
    p.setPen(text_color)
    font = p.font()
    font.setBold(True)
    font.setPixelSize(max(8, int(min(rect.width(), rect.height()) * 0.55)))
    p.setFont(font)
    p.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"+{int(count)}")
    p.restore()
