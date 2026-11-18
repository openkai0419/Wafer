import pytest
from PySide6 import QtGui

from wafer.qt.palette import DARK, LIGHT
from wafer.qt.theme import ThemeManager
from wafer.app.viewer.widgets.overlay_stack import overlay_colors


@pytest.fixture(params=[DARK, LIGHT], ids=["dark", "light"])
def palette(request, monkeypatch):
    monkeypatch.setattr(ThemeManager.instance(), "_palette", request.param)
    return request.param


def test_notifications_use_the_theme_colors(palette):
    bg, text = overlay_colors("info")
    assert bg.rgb() == QtGui.QColor(palette.bg_elevated).rgb()
    assert text == QtGui.QColor(palette.text_primary)

    bg, _text = overlay_colors("error")
    assert bg.rgb() == QtGui.QColor(palette.error).rgb()
