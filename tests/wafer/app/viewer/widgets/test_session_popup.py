import pytest
from unittest.mock import MagicMock
from wafer.core.color.theme import ThemeManager
from wafer.app.viewer.widgets.session_popup import (
    SessionItemWidget, SessionPopup, ColorDot, ColorPalette,
)


def _make_entry(sid='s1', name='Work', color=''):
    e = MagicMock()
    e.session_id = sid
    e.name = name
    e.color = color
    return e


class TestColorDot:

    def test_creates(self, qtbot):
        dot = ColorDot('#FF0000')
        qtbot.addWidget(dot)
        assert dot._color == '#FF0000'

    def test_empty_color(self, qtbot):
        dot = ColorDot('')
        qtbot.addWidget(dot)
        assert dot._color == ''


class TestColorPalette:

    def test_emits_color(self, qtbot):
        palette = ColorPalette()
        qtbot.addWidget(palette)
        with qtbot.waitSignal(palette.color_selected) as sig:
            palette.layout().itemAt(0).widget().click()
        assert sig.args[0].startswith('#')

    def test_clear_button(self, qtbot):
        from wafer.app.viewer.session import SESSION_COLORS
        palette = ColorPalette()
        qtbot.addWidget(palette)
        clear_btn = palette.layout().itemAt(len(SESSION_COLORS)).widget()
        with qtbot.waitSignal(palette.color_selected) as sig:
            clear_btn.click()
        assert sig.args == ['']


class TestSessionItemWidget:

    def test_label_text(self, qtbot):
        item = SessionItemWidget('s1', 'Work')
        qtbot.addWidget(item)
        assert item._label.text() == 'Work'

    def test_current_label(self, qtbot):
        item = SessionItemWidget('s1', 'Work', current=True)
        qtbot.addWidget(item)
        assert item._label.text() == 'Work'
        p = ThemeManager.instance().palette
        assert p.text_accent in item._label.styleSheet()

    def test_not_current_label(self, qtbot):
        item = SessionItemWidget('s1', 'Work', current=False)
        qtbot.addWidget(item)
        p = ThemeManager.instance().palette
        assert p.text_primary in item._label.styleSheet()

    def test_alive_dot_present(self, qtbot):
        item = SessionItemWidget('s1', 'Work', alive=True)
        qtbot.addWidget(item)
        assert item.layout().count() == 5

    def test_no_alive_dot_no_color(self, qtbot):
        item = SessionItemWidget('s1', 'Work', alive=False)
        qtbot.addWidget(item)
        assert item.layout().count() == 4

    def test_color_dot_present(self, qtbot):
        item = SessionItemWidget('s1', 'Work', color='#FF0000')
        qtbot.addWidget(item)
        assert item.layout().count() == 5

    def test_rename_signal(self, qtbot):
        item = SessionItemWidget('s1', 'Work')
        qtbot.addWidget(item)
        layout = item.layout()
        rename_btn = layout.itemAt(layout.count() - 2).widget()
        with qtbot.waitSignal(item.rename_requested) as sig:
            rename_btn.click()
        assert sig.args == ['s1']

    def test_delete_signal(self, qtbot):
        item = SessionItemWidget('s1', 'Work')
        qtbot.addWidget(item)
        layout = item.layout()
        delete_btn = layout.itemAt(layout.count() - 1).widget()
        with qtbot.waitSignal(item.delete_requested) as sig:
            delete_btn.click()
        assert sig.args == ['s1']

    def test_color_signal(self, qtbot):
        item = SessionItemWidget('s1', 'Work')
        qtbot.addWidget(item)
        layout = item.layout()
        color_btn = layout.itemAt(layout.count() - 3).widget()
        with qtbot.waitSignal(item.color_requested) as sig:
            color_btn.click()
        assert sig.args == ['s1']

    def test_hover_changes_background(self, qtbot):
        from PySide6 import QtCore, QtGui
        item = SessionItemWidget('s1', 'Work')
        qtbot.addWidget(item)
        enter_ev = QtGui.QEnterEvent(
            QtCore.QPointF(5, 5), QtCore.QPointF(5, 5), QtCore.QPointF(5, 5),
        )
        item.enterEvent(enter_ev)
        assert 'background' in item.styleSheet()
        item.leaveEvent(QtCore.QEvent(QtCore.QEvent.Leave))
        assert 'background' not in item.styleSheet()

    def test_press_changes_background(self, qtbot):
        from PySide6 import QtCore, QtGui
        item = SessionItemWidget('s1', 'Work')
        qtbot.addWidget(item)
        press_ev = QtGui.QMouseEvent(
            QtCore.QEvent.MouseButtonPress,
            QtCore.QPointF(5, 5), QtCore.Qt.LeftButton,
            QtCore.Qt.LeftButton, QtCore.Qt.NoModifier,
        )
        item.mousePressEvent(press_ev)
        p = ThemeManager.instance().palette
        assert p.bg_pressed in item.styleSheet()

    def test_release_emits_open(self, qtbot):
        from PySide6 import QtCore, QtGui
        item = SessionItemWidget('s1', 'Work')
        qtbot.addWidget(item)
        release_ev = QtGui.QMouseEvent(
            QtCore.QEvent.MouseButtonRelease,
            QtCore.QPointF(5, 5), QtCore.Qt.LeftButton,
            QtCore.Qt.LeftButton, QtCore.Qt.NoModifier,
        )
        with qtbot.waitSignal(item.open_requested) as sig:
            item.mouseReleaseEvent(release_ev)
        assert sig.args == ['s1']


class TestSessionPopup:

    def test_populate_items(self, qtbot):
        popup = SessionPopup()
        qtbot.addWidget(popup)
        popup.populate([_make_entry('s1', 'A', '#FF0000'), _make_entry('s2', 'B')])
        assert popup._list_layout.count() == 2

    def test_populate_marks_current(self, qtbot):
        popup = SessionPopup()
        qtbot.addWidget(popup)
        popup.populate(
            [_make_entry('s1', 'A'), _make_entry('s2', 'B')],
            current_session_id='s1',
        )
        row = popup._list_layout.itemAt(0).widget()
        p = ThemeManager.instance().palette
        assert p.text_accent in row._label.styleSheet()
        row2 = popup._list_layout.itemAt(1).widget()
        assert p.text_primary in row2._label.styleSheet()

    def test_populate_empty_placeholder(self, qtbot):
        popup = SessionPopup()
        qtbot.addWidget(popup)
        popup.populate([])
        assert popup._list_layout.count() == 1

    def test_repopulate_clears_old(self, qtbot):
        popup = SessionPopup()
        qtbot.addWidget(popup)
        popup.populate([_make_entry('s1', 'A'), _make_entry('s2', 'B')])
        popup.populate([_make_entry('s3', 'C')])
        assert popup._list_layout.count() == 1

    def test_create_signal(self, qtbot):
        popup = SessionPopup()
        qtbot.addWidget(popup)
        popup.show()
        with qtbot.waitSignal(popup.session_create):
            popup._on_create()

    def test_open_closes_popup(self, qtbot):
        popup = SessionPopup()
        qtbot.addWidget(popup)
        popup.populate([_make_entry('s1', 'A')])
        popup.show()
        with qtbot.waitSignal(popup.session_open) as sig:
            popup._on_open('s1')
        assert sig.args == ['s1']
        assert not popup.isVisible()
