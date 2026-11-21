import pytest
from PySide6 import QtCore, QtGui, QtWidgets

from wafer.qt.palette import DARK, LIGHT
from wafer.qt.theme import ThemeManager
from wafer.app.viewer.widgets.progress_bar import ThinProgressBar, TooltipPopup


@pytest.fixture(params=[DARK, LIGHT], ids=["dark", "light"])
def palette(request, monkeypatch):
    monkeypatch.setattr(ThemeManager.instance(), "_palette", request.param)
    return request.param


def test_progress_bar_paints_the_success_color_like_the_webui(qtbot, palette):
    bar = ThinProgressBar()
    qtbot.addWidget(bar)
    bar.resize(200, 10)
    bar._maximum = 10
    bar._animated_value = 5
    bar._color_opacity = 1.0

    assert bar.grab().toImage().pixelColor(20, 1).name() == QtGui.QColor(palette.success).name()


def test_progress_bar_fades_out_when_it_finishes_right_after_it_starts(qtbot):
    bar = ThinProgressBar()
    qtbot.addWidget(bar)

    bar.setMaximum(3)
    bar.setProgress(3)

    qtbot.waitUntil(lambda: bar._opacity_animation.state() == QtCore.QAbstractAnimation.Stopped)
    assert bar.getColorOpacity() == 0.0 and not bar._glow_timer.isActive()


def test_progress_bar_stays_shown_when_it_restarts_right_after_it_finishes(qtbot):
    bar = ThinProgressBar()
    qtbot.addWidget(bar)
    bar.setMaximum(3)
    qtbot.waitUntil(lambda: bar.getColorOpacity() == 1.0)

    bar.setProgress(3)
    bar.setMaximum(6)

    qtbot.waitUntil(lambda: bar._opacity_animation.state() == QtCore.QAbstractAnimation.Stopped)
    assert bar.getColorOpacity() == 1.0 and bar._glow_timer.isActive()


def test_tooltip_uses_the_theme_colors(qtbot, palette):
    tooltip = TooltipPopup("1 / 2")
    qtbot.addWidget(tooltip)

    style = tooltip.label.styleSheet()
    assert palette.text_primary in style and palette.bg_elevated in style



def test_hover_proxy_follows_a_width_change_made_while_hidden(qtbot):
    window = QtWidgets.QWidget()
    qtbot.addWidget(window)
    QtWidgets.QVBoxLayout(window)
    panel = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(panel)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    bar = ThinProgressBar()
    layout.addWidget(QtWidgets.QPushButton("top"))
    layout.addWidget(bar)
    layout.addWidget(QtWidgets.QPushButton("bottom"))
    window.layout().addWidget(panel)
    window.resize(300, 200)
    window.show()
    qtbot.waitUntil(lambda: getattr(bar, "_hover_proxy", None) is not None)
    proxy = bar._hover_proxy
    margin = proxy._margin

    panel.hide()
    window.resize(600, 200)
    qtbot.waitUntil(lambda: window.width() == 600)
    panel.show()
    qtbot.waitUntil(lambda: bar.isVisible() and bar.width() > 500)

    assert proxy.geometry() == bar.geometry().adjusted(-margin, -margin, margin, margin)
    window.close()
