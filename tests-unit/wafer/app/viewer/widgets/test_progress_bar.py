import pytest
from PySide6 import QtGui

from wafer.qt.palette import DARK, LIGHT
from wafer.qt.theme import ThemeManager
from wafer.app.viewer.widgets.progress_bar import ThinProgressBar, TooltipPopup


@pytest.fixture(params=[DARK, LIGHT], ids=["dark", "light"])
def palette(request, monkeypatch):
    monkeypatch.setattr(ThemeManager.instance(), "_palette", request.param)
    return request.param


def test_progress_bar_paints_the_accent_color(qtbot, palette):
    bar = ThinProgressBar()
    qtbot.addWidget(bar)
    bar.resize(200, 10)
    bar._maximum = 10
    bar._animated_value = 5
    bar._color_opacity = 1.0

    assert bar.grab().toImage().pixelColor(20, 1).name() == QtGui.QColor(palette.accent).name()


def test_tooltip_uses_the_theme_colors(qtbot, palette):
    tooltip = TooltipPopup("1 / 2")
    qtbot.addWidget(tooltip)

    style = tooltip.label.styleSheet()
    assert palette.text_primary in style and palette.bg_elevated in style
