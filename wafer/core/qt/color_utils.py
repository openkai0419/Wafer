from __future__ import annotations

from PySide6.QtGui import QColor


def mix_colors(base: str | QColor, tint: str | QColor, ratio: float) -> QColor:
    base_color = QColor(base)
    tint_color = QColor(tint)
    amount = max(0.0, min(1.0, ratio))
    keep = 1.0 - amount
    return QColor(
        round(base_color.red() * keep + tint_color.red() * amount),
        round(base_color.green() * keep + tint_color.green() * amount),
        round(base_color.blue() * keep + tint_color.blue() * amount),
        round(base_color.alpha() * keep + tint_color.alpha() * amount),
    )
