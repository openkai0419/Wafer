import pytest
from unittest.mock import MagicMock
from wafer.core.color.theme import ThemeManager
from wafer.app.viewer.widgets.profile_popup import (
    ClickableColorDot,
    ProfileItemWidget,
    ProfilePopup,
    ColorPalette,
)


def _make_entry(sid="s1", name="Work", color=""):
    e = MagicMock()
    e.profile_id = sid
    e.name = name
    e.color = color
    return e


class TestClickableColorDot:
    def test_creates_with_color(self, qtbot):
        dot = ClickableColorDot("#FF0000")
        qtbot.addWidget(dot)
        assert dot._color == "#FF0000"

    def test_empty_color(self, qtbot):
        dot = ClickableColorDot("")
        qtbot.addWidget(dot)
        assert dot._color == ""

    def test_set_color(self, qtbot):
        dot = ClickableColorDot("#FF0000")
        qtbot.addWidget(dot)
        dot.set_color("#00FF00")
        assert dot._color == "#00FF00"

    def test_click_emits_signal(self, qtbot):
        from PySide6 import QtCore, QtGui

        dot = ClickableColorDot("#FF0000")
        qtbot.addWidget(dot)
        release_ev = QtGui.QMouseEvent(
            QtCore.QEvent.MouseButtonRelease,
            QtCore.QPointF(5, 5),
            QtCore.Qt.LeftButton,
            QtCore.Qt.LeftButton,
            QtCore.Qt.NoModifier,
        )
        with qtbot.waitSignal(dot.clicked):
            dot.mouseReleaseEvent(release_ev)


class TestColorPalette:
    def test_emits_color(self, qtbot):
        palette = ColorPalette()
        qtbot.addWidget(palette)
        with qtbot.waitSignal(palette.color_selected) as sig:
            palette.layout().itemAt(0).widget().click()
        assert sig.args[0].startswith("#")

    def test_clear_button(self, qtbot):
        from wafer.core.profile import PROFILE_COLORS

        palette = ColorPalette()
        qtbot.addWidget(palette)
        clear_btn = palette.layout().itemAt(len(PROFILE_COLORS)).widget()
        with qtbot.waitSignal(palette.color_selected) as sig:
            clear_btn.click()
        assert sig.args == [""]


class TestProfileItemWidget:
    def test_label_text(self, qtbot):
        item = ProfileItemWidget("s1", "Work")
        qtbot.addWidget(item)
        assert item._label.text() == "Work"

    def test_current_label(self, qtbot):
        item = ProfileItemWidget("s1", "Work", current=True)
        qtbot.addWidget(item)
        assert item._label.text() == "Work"
        p = ThemeManager.instance().palette
        assert p.text_accent in item._label.styleSheet()

    def test_not_current_label(self, qtbot):
        item = ProfileItemWidget("s1", "Work", current=False)
        qtbot.addWidget(item)
        p = ThemeManager.instance().palette
        assert p.text_primary in item._label.styleSheet()

    def test_widget_count(self, qtbot):
        item = ProfileItemWidget("s1", "Work")
        qtbot.addWidget(item)
        assert item.layout().count() == 5

    def test_color_dot_present(self, qtbot):
        item = ProfileItemWidget("s1", "Work", color="#FF0000")
        qtbot.addWidget(item)
        assert item.layout().count() == 5

    def test_rename_signal(self, qtbot):
        item = ProfileItemWidget("s1", "Work")
        qtbot.addWidget(item)
        layout = item.layout()
        rename_btn = layout.itemAt(layout.count() - 2).widget()
        with qtbot.waitSignal(item.rename_requested) as sig:
            rename_btn.click()
        assert sig.args == ["s1"]

    def test_delete_signal(self, qtbot):
        item = ProfileItemWidget("s1", "Work")
        qtbot.addWidget(item)
        layout = item.layout()
        delete_btn = layout.itemAt(layout.count() - 1).widget()
        with qtbot.waitSignal(item.delete_requested) as sig:
            delete_btn.click()
        assert sig.args == ["s1"]

    def test_color_signal(self, qtbot):
        from PySide6 import QtCore, QtGui

        item = ProfileItemWidget("s1", "Work", color="#FF0000")
        qtbot.addWidget(item)
        dot = item.color_dot
        release_ev = QtGui.QMouseEvent(
            QtCore.QEvent.MouseButtonRelease,
            QtCore.QPointF(3, 3),
            QtCore.Qt.LeftButton,
            QtCore.Qt.LeftButton,
            QtCore.Qt.NoModifier,
        )
        with qtbot.waitSignal(item.color_requested) as sig:
            dot.mouseReleaseEvent(release_ev)
        assert sig.args == ["s1"]

    def test_hover_changes_background(self, qtbot):
        from PySide6 import QtCore, QtGui

        item = ProfileItemWidget("s1", "Work")
        qtbot.addWidget(item)
        enter_ev = QtGui.QEnterEvent(
            QtCore.QPointF(5, 5),
            QtCore.QPointF(5, 5),
            QtCore.QPointF(5, 5),
        )
        item.enterEvent(enter_ev)
        assert "background" in item.styleSheet()
        item.leaveEvent(QtCore.QEvent(QtCore.QEvent.Leave))
        assert "background" not in item.styleSheet()

    def test_press_changes_background(self, qtbot):
        from PySide6 import QtCore, QtGui

        item = ProfileItemWidget("s1", "Work")
        qtbot.addWidget(item)
        press_ev = QtGui.QMouseEvent(
            QtCore.QEvent.MouseButtonPress,
            QtCore.QPointF(5, 5),
            QtCore.Qt.LeftButton,
            QtCore.Qt.LeftButton,
            QtCore.Qt.NoModifier,
        )
        item.mousePressEvent(press_ev)
        p = ThemeManager.instance().palette
        assert p.bg_pressed in item.styleSheet()

    def test_release_emits_open(self, qtbot):
        from PySide6 import QtCore, QtGui

        item = ProfileItemWidget("s1", "Work")
        qtbot.addWidget(item)
        release_ev = QtGui.QMouseEvent(
            QtCore.QEvent.MouseButtonRelease,
            QtCore.QPointF(5, 5),
            QtCore.Qt.LeftButton,
            QtCore.Qt.LeftButton,
            QtCore.Qt.NoModifier,
        )
        with qtbot.waitSignal(item.open_requested) as sig:
            item.mouseReleaseEvent(release_ev)
        assert sig.args == ["s1"]


class TestProfilePopup:
    def test_populate_items(self, qtbot):
        popup = ProfilePopup()
        qtbot.addWidget(popup)
        popup.populate([_make_entry("s1", "A", "#FF0000"), _make_entry("s2", "B")])
        assert popup._list_layout.count() == 2

    def test_populate_marks_current(self, qtbot):
        popup = ProfilePopup()
        qtbot.addWidget(popup)
        popup.populate(
            [_make_entry("s1", "A"), _make_entry("s2", "B")],
            current_profile_id="s1",
        )
        row = popup._list_layout.itemAt(0).widget()
        p = ThemeManager.instance().palette
        assert p.text_accent in row._label.styleSheet()
        row2 = popup._list_layout.itemAt(1).widget()
        assert p.text_primary in row2._label.styleSheet()

    def test_populate_empty_placeholder(self, qtbot):
        popup = ProfilePopup()
        qtbot.addWidget(popup)
        popup.populate([])
        assert popup._list_layout.count() == 1

    def test_repopulate_clears_old(self, qtbot):
        popup = ProfilePopup()
        qtbot.addWidget(popup)
        popup.populate([_make_entry("s1", "A"), _make_entry("s2", "B")])
        popup.populate([_make_entry("s3", "C")])
        assert popup._list_layout.count() == 1

    def test_create_signal(self, qtbot):
        popup = ProfilePopup()
        qtbot.addWidget(popup)
        popup.show()
        with qtbot.waitSignal(popup.profile_create):
            popup._on_create()

    def test_open_closes_popup(self, qtbot):
        popup = ProfilePopup()
        qtbot.addWidget(popup)
        popup.populate([_make_entry("s1", "A")])
        popup.show()
        with qtbot.waitSignal(popup.profile_open) as sig:
            popup._on_open("s1")
        assert sig.args == ["s1"]
        assert not popup.isVisible()

    def test_inline_color_palette_toggle(self, qtbot):
        popup = ProfilePopup()
        qtbot.addWidget(popup)
        popup.populate([_make_entry("s1", "A", "#FF0000")])
        assert popup._list_layout.count() == 1
        popup._on_color_requested("s1")
        assert popup._list_layout.count() == 2
        assert popup._active_palette is not None
        popup._on_color_requested("s1")
        assert popup._active_palette is None

    def test_inline_color_emits_changed(self, qtbot):
        popup = ProfilePopup()
        qtbot.addWidget(popup)
        popup.populate([_make_entry("s1", "A", "#FF0000")])
        popup._on_color_requested("s1")
        palette = popup._active_palette
        with qtbot.waitSignal(popup.profile_color_changed) as sig:
            palette.color_selected.emit("#00FF00")
        assert sig.args == ["s1", "#00FF00"]
        row = popup._list_layout.itemAt(0).widget()
        assert row.color_dot._color == "#00FF00"
