import pytest
from PySide6 import QtCore, QtGui, QtWidgets
from wafer.app.viewer.preview.meta_viewer import MetaRowWidget, CollapsibleCard
from wafer.utils.formatting import dpix


def test_meta_row_widget_has_key_role_style(qtbot):
    w = MetaRowWidget(0, {"key": "value"})
    qtbot.addWidget(w)
    ss = w.styleSheet()
    assert "keyRole" in ss
    assert "font-weight" in ss


def test_collapsible_card_default_expanded(qtbot):
    card = CollapsibleCard("test", "test_key")
    qtbot.addWidget(card)
    assert card.expanded is True


def test_collapsible_card_toggle(qtbot):
    card = CollapsibleCard("test", "test_key")
    qtbot.addWidget(card)
    card.set_expanded(False)
    assert card.expanded is False
    card.set_expanded(True)
    assert card.expanded is True


def test_collapsible_card_set_content(qtbot):
    card = CollapsibleCard("test", "test_key")
    qtbot.addWidget(card)
    label = QtWidgets.QLabel("hello")
    card.set_content_widget(label)
    assert card.content_widget() is label


def test_collapsible_card_replace_content(qtbot):
    card = CollapsibleCard("test", "test_key")
    qtbot.addWidget(card)
    first = QtWidgets.QLabel("first")
    card.set_content_widget(first)
    second = QtWidgets.QLabel("second")
    card.set_content_widget(second)
    assert card.content_widget() is second


def test_collapsible_card_signal_via_click(qtbot):
    card = CollapsibleCard("test", "test_key")
    qtbot.addWidget(card)
    card.show()
    card.resize(200, 100)
    received = []
    card.toggled_card.connect(lambda key, exp: received.append((key, exp)))
    click_pos = QtCore.QPointF(100, dpix(8))
    event = QtGui.QMouseEvent(
        QtCore.QEvent.Type.MouseButtonPress,
        click_pos,
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.MouseButton.LeftButton,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )
    card.mousePressEvent(event)
    assert len(received) == 1
    assert received[0] == ("test_key", False)


def test_collapsible_card_title_with_count(qtbot):
    card = CollapsibleCard("mysection", "ms")
    qtbot.addWidget(card)
    card.update_title_count(5)
    assert "(5)" in card.title()
    card.update_title_count(0)
    assert "(0)" not in card.title()


def test_collapsible_card_is_frame(qtbot):
    card = CollapsibleCard("test", "test_key")
    qtbot.addWidget(card)
    assert isinstance(card, QtWidgets.QFrame)


def test_collapsible_card_content_hidden_when_collapsed(qtbot):
    card = CollapsibleCard("test", "test_key")
    qtbot.addWidget(card)
    label = QtWidgets.QLabel("content")
    card.set_content_widget(label)
    card.set_expanded(False)
    assert label.isHidden()
    card.set_expanded(True)
    assert not label.isHidden()
