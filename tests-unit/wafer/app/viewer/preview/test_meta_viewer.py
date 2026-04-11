import pytest
from PySide6 import QtWidgets
from wafer.app.viewer.preview.meta_viewer import MetaRowWidget, CollapsibleSection
from wafer.utils.formatting import dpix


def test_stylesheet_contains_resolved_border_radius(qtbot):
    w = MetaRowWidget(0, {"key": "value"})
    qtbot.addWidget(w)
    ss = w.styleSheet()
    expected = f"border-radius: {dpix(12)}px"
    assert expected in ss
    assert "{dpix(12)}" not in ss


def test_collapsible_section_default_expanded(qtbot):
    sec = CollapsibleSection("Test", "test_key")
    qtbot.addWidget(sec)
    assert sec.expanded is True
    assert not sec._content_area.isHidden()


def test_collapsible_section_toggle(qtbot):
    sec = CollapsibleSection("Test", "test_key")
    qtbot.addWidget(sec)
    sec.set_expanded(False)
    assert sec.expanded is False
    assert sec._content_area.isHidden()
    sec.set_expanded(True)
    assert sec.expanded is True
    assert not sec._content_area.isHidden()


def test_collapsible_section_set_content(qtbot):
    sec = CollapsibleSection("Test", "test_key")
    qtbot.addWidget(sec)
    label = QtWidgets.QLabel("hello")
    sec.set_content_widget(label)
    assert sec.content_widget() is label


def test_collapsible_section_replace_content(qtbot):
    sec = CollapsibleSection("Test", "test_key")
    qtbot.addWidget(sec)
    first = QtWidgets.QLabel("first")
    sec.set_content_widget(first)
    second = QtWidgets.QLabel("second")
    sec.set_content_widget(second)
    assert sec.content_widget() is second


def test_collapsible_section_signal(qtbot):
    sec = CollapsibleSection("Test", "test_key")
    qtbot.addWidget(sec)
    received = []
    sec.toggled.connect(lambda key, exp: received.append((key, exp)))
    sec._header.click()
    assert len(received) == 1
    assert received[0] == ("test_key", False)


def test_collapsible_section_title_with_count(qtbot):
    sec = CollapsibleSection("MySection", "ms")
    qtbot.addWidget(sec)
    sec.update_title_count(5)
    assert "(5)" in sec._header.text()
    sec.update_title_count(0)
    assert "(0)" not in sec._header.text()
