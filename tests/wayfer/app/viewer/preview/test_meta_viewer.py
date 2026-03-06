import pytest
from PySide6 import QtWidgets
from wayfer.app.viewer.preview.meta_viewer import MetaRowWidget
from wayfer.utils.formatting import dpix


def test_stylesheet_contains_resolved_border_radius(qtbot):
    w = MetaRowWidget(0, {"key": "value"})
    qtbot.addWidget(w)
    ss = w.styleSheet()
    expected = f"border-radius: {dpix(12)}px"
    assert expected in ss
    assert "{dpix(12)}" not in ss
