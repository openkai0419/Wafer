from __future__ import annotations

from dataclasses import dataclass


def _hex(color) -> str:
    return color.name()


def _rgba(color, alpha: float) -> str:
    return f"rgba({color.red()},{color.green()},{color.blue()},{alpha})"


def _mix(c1, c2, ratio: float = 0.5):
    from PySide6 import QtGui

    return QtGui.QColor(
        int(c1.red() * (1 - ratio) + c2.red() * ratio),
        int(c1.green() * (1 - ratio) + c2.green() * ratio),
        int(c1.blue() * (1 - ratio) + c2.blue() * ratio),
    )


@dataclass(frozen=True)
class ThemePalette:
    bg_primary: str
    bg_secondary: str
    bg_tertiary: str
    bg_elevated: str
    bg_hover: str
    bg_pressed: str

    text_primary: str
    text_secondary: str
    text_tertiary: str
    text_muted: str
    text_accent: str

    accent: str
    accent_text: str

    border_default: str
    border_subtle: str

    success: str
    warning: str
    error: str
    info: str

    @staticmethod
    def from_system() -> ThemePalette:
        from PySide6 import QtGui

        app = QtGui.QGuiApplication.instance()
        if app is None:
            return DARK
        qp = app.palette()
        window = qp.color(QtGui.QPalette.Window)
        window_text = qp.color(QtGui.QPalette.WindowText)
        base = qp.color(QtGui.QPalette.Base)
        mid = qp.color(QtGui.QPalette.Mid)
        midlight = qp.color(QtGui.QPalette.Midlight)
        highlight = qp.color(QtGui.QPalette.Highlight)
        placeholder = qp.color(QtGui.QPalette.PlaceholderText)
        link = qp.color(QtGui.QPalette.Link)
        light = qp.color(QtGui.QPalette.Light)
        dark = window.value() < 128
        overlay = window_text if dark else QtGui.QColor(0, 0, 0)
        if dark:
            accent = link if abs(link.value() - window.value()) > abs(highlight.value() - window.value()) else highlight
            border = light if abs(light.value() - window.value()) > abs(mid.value() - window.value()) else mid
            muted = QtGui.QColor(window_text).darker(160) if abs(placeholder.value() - window_text.value()) < 30 else placeholder
        else:
            accent = highlight
            border = mid
            muted = placeholder
        return ThemePalette(
            bg_primary=_hex(window),
            bg_secondary=_hex(base),
            bg_tertiary=_hex(_mix(window, base, 0.5)),
            bg_elevated=_hex(base),
            bg_hover=_rgba(overlay, 0.08 if dark else 0.06),
            bg_pressed=_rgba(overlay, 0.15 if dark else 0.12),
            text_primary=_hex(window_text),
            text_secondary=_hex(mid if not dark else midlight),
            text_tertiary=_hex(_mix(window_text, mid if not dark else midlight, 0.5)),
            text_muted=_hex(muted),
            text_accent=_hex(accent),
            accent="#3B80FF",
            accent_text="#ffffff",
            border_default=_hex(border),
            border_subtle=_hex(midlight if not dark else QtGui.QColor(border).darker(120)),
            success="#4CAF50" if dark else "#2e7d32",
            warning="#FFA726" if dark else "#e65100",
            error="#EF5350" if dark else "#c62828",
            info=_hex(accent),
        )


DARK = ThemePalette(
    bg_primary="#1e1e1e",
    bg_secondary="#2b2b2b",
    bg_tertiary="#252525",
    bg_elevated="#2b2b2b",
    bg_hover="rgba(255,255,255,0.08)",
    bg_pressed="rgba(255,255,255,0.15)",
    text_primary="#ccc",
    text_secondary="#aaa",
    text_tertiary="#999",
    text_muted="#888",
    text_accent="#7cb3ff",
    accent="#3B80FF",
    accent_text="#ffffff",
    border_default="#555",
    border_subtle="#444",
    success="#4CAF50",
    warning="#FFA726",
    error="#EF5350",
    info="#7cb3ff",
)

LIGHT = ThemePalette(
    bg_primary="#ffffff",
    bg_secondary="#f5f5f5",
    bg_tertiary="#fafafa",
    bg_elevated="#ffffff",
    bg_hover="rgba(0,0,0,0.06)",
    bg_pressed="rgba(0,0,0,0.12)",
    text_primary="#1e1e1e",
    text_secondary="#555",
    text_tertiary="#777",
    text_muted="#888",
    text_accent="#1a73e8",
    accent="#1a73e8",
    accent_text="#ffffff",
    border_default="#ccc",
    border_subtle="#e0e0e0",
    success="#2e7d32",
    warning="#e65100",
    error="#c62828",
    info="#1a73e8",
)
