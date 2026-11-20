import pytest
from PySide6 import QtGui

from wafer.qt.palette import DARK, LIGHT
from wafer.qt.theme import ThemeManager
from wafer.app.viewer.widgets.loading_overlay import OverlayLoadingIndicator


@pytest.fixture(params=[DARK, LIGHT], ids=["dark", "light"])
def palette(request, monkeypatch):
    monkeypatch.setattr(ThemeManager.instance(), "_palette", request.param)
    return request.param


def test_loading_indicator_uses_the_theme_background(qtbot, palette):
    indicator = OverlayLoadingIndicator()
    qtbot.addWidget(indicator)
    expected = QtGui.QColor(palette.bg_elevated)

    color = indicator.grab().toImage().pixelColor(indicator.width() // 2, 2)

    assert abs(color.red() - expected.red()) <= 2 and abs(color.green() - expected.green()) <= 2
