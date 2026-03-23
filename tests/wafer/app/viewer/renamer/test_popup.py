import pytest
from pathlib import Path
from unittest.mock import MagicMock

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from wafer.plugin.rename.base import DropdownButton, ToggleButton, RenameConfigWidget
from wafer.app.viewer.renamer._popup import ColumnSettingsPopup, _ClickOutsideFilter
from wafer.app.viewer.renamer._engine import RenameColumn, PostProcess
from wafer.builtins.rename_sources import (
    NameSource, FixedSource, MetaSource, ExtSource,
    SequentialSource, DateSource, RandomSource,
)


class TestToggleButton:

    def test_initial_unchecked(self, qtbot):
        btn = ToggleButton('Trim')
        qtbot.addWidget(btn)
        assert not btn.isChecked()
        assert '\u25b8' in btn.text()

    def test_initial_checked(self, qtbot):
        btn = ToggleButton('Trim', True)
        qtbot.addWidget(btn)
        assert btn.isChecked()
        assert '\u25be' in btn.text()

    def test_toggle_emits_and_updates(self, qtbot):
        btn = ToggleButton('Test')
        qtbot.addWidget(btn)
        received = []
        btn.toggled.connect(received.append)
        btn.setChecked(True)
        assert received == [True]
        assert '\u25be' in btn.text()

    def test_is_checkable_pushbutton(self, qtbot):
        btn = ToggleButton('X')
        qtbot.addWidget(btn)
        assert isinstance(btn, QtWidgets.QPushButton)
        assert btn.isCheckable()


class TestDropdownButton:

    def test_initial_value(self, qtbot):
        btn = DropdownButton('Key', ['a', 'b', 'c'], 'b')
        qtbot.addWidget(btn)
        assert btn.value() == 'b'
        assert 'b' in btn.text()

    def test_default_first_choice(self, qtbot):
        btn = DropdownButton('Key', ['x', 'y'])
        qtbot.addWidget(btn)
        assert btn.value() == 'x'

    def test_empty_choices(self, qtbot):
        btn = DropdownButton('Key', [])
        qtbot.addWidget(btn)
        assert btn.value() == ''

    def test_pick_emits_signal(self, qtbot):
        btn = DropdownButton('Key', ['a', 'b', 'c'], 'a')
        qtbot.addWidget(btn)
        received = []
        btn.value_changed.connect(received.append)
        btn._pick('c')
        assert received == ['c']
        assert btn.value() == 'c'

    def test_is_qpushbutton(self, qtbot):
        btn = DropdownButton('Test', ['on', 'off'])
        qtbot.addWidget(btn)
        assert isinstance(btn, QtWidgets.QPushButton)

    def test_has_cursor(self, qtbot):
        btn = DropdownButton('Test', ['on', 'off'])
        qtbot.addWidget(btn)
        assert btn.cursor().shape() == Qt.PointingHandCursor


class TestColumnSettingsPopup:

    def test_window_flags_tool(self, qtbot):
        col = RenameColumn(NameSource())
        popup = ColumnSettingsPopup(col)
        qtbot.addWidget(popup)
        assert popup.windowFlags() & Qt.Tool
        assert popup.windowFlags() & Qt.FramelessWindowHint

    def test_click_filter_installed(self, qtbot):
        col = RenameColumn(NameSource())
        popup = ColumnSettingsPopup(col)
        qtbot.addWidget(popup)
        assert isinstance(popup._click_filter, _ClickOutsideFilter)

    def test_close_removes_event_filter(self, qtbot):
        col = RenameColumn(NameSource())
        popup = ColumnSettingsPopup(col)
        qtbot.addWidget(popup)
        popup.show()
        popup.close()
        assert popup._click_filter is None

    def test_changed_signal_on_post_toggle(self, qtbot):
        post = PostProcess(prefix='pre_')
        col = RenameColumn(NameSource(), post)
        popup = ColumnSettingsPopup(col)
        qtbot.addWidget(popup)
        received = []
        popup.changed.connect(lambda: received.append(True))
        post.prefix = 'new_'
        popup.changed.emit()
        assert len(received) == 1

    def test_meta_source_initial_key(self, qtbot):
        src = MetaSource()
        col = RenameColumn(src)
        popup = ColumnSettingsPopup(
            col, meta_keys=['width', 'height', 'dpi'],
        )
        qtbot.addWidget(popup)
        assert src.key == 'width'

    def test_meta_source_preserves_key(self, qtbot):
        src = MetaSource(key='height')
        col = RenameColumn(src)
        popup = ColumnSettingsPopup(
            col, meta_keys=['width', 'height', 'dpi'],
        )
        qtbot.addWidget(popup)
        assert src.key == 'height'

    def test_resize_and_clamp(self, qtbot):
        col = RenameColumn(NameSource())
        popup = ColumnSettingsPopup(col)
        qtbot.addWidget(popup)
        popup.move(0, 0)
        popup.adjustSize()
        popup._resize_and_clamp()
        screen = QtWidgets.QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            assert popup.x() >= geo.left()
            assert popup.y() >= geo.top()

    def test_ext_column(self, qtbot):
        col = RenameColumn(ExtSource())
        popup = ColumnSettingsPopup(col, is_ext=True)
        qtbot.addWidget(popup)
        assert popup.windowFlags() & Qt.Tool

    def test_source_config_widget_embedded(self, qtbot):
        src = FixedSource('hello')
        col = RenameColumn(src)
        popup = ColumnSettingsPopup(col)
        qtbot.addWidget(popup)
        config_widgets = popup.findChildren(RenameConfigWidget)
        assert len(config_widgets) == 1

    def test_sequential_resequence_signal(self, qtbot):
        src = SequentialSource()
        col = RenameColumn(src)
        popup = ColumnSettingsPopup(col)
        qtbot.addWidget(popup)
        received = []
        popup.resequence_requested.connect(lambda: received.append(True))
        config_w = popup.findChild(RenameConfigWidget)
        config_w.resequence_requested.emit()
        assert len(received) == 1

    def test_no_isinstance_in_popup(self):
        import inspect
        from wafer.app.viewer.renamer import _popup
        source_text = inspect.getsource(_popup)
        assert 'isinstance' not in source_text
        assert 'hasattr' not in source_text

    def test_follows_parent_window_on_move(self, qtbot):
        parent = QtWidgets.QWidget()
        parent.move(100, 100)
        parent.show()
        qtbot.addWidget(parent)
        col = RenameColumn(NameSource())
        popup = ColumnSettingsPopup(col, parent=parent)
        qtbot.addWidget(popup)
        popup.move(150, 200)
        popup.show()
        qtbot.waitExposed(popup)
        offset = popup.pos() - parent.window().pos()
        parent.move(300, 300)
        QtWidgets.QApplication.processEvents()
        assert popup.pos() == parent.window().pos() + offset

    def test_anchor_cleanup_on_close(self, qtbot):
        parent = QtWidgets.QWidget()
        parent.show()
        qtbot.addWidget(parent)
        col = RenameColumn(NameSource())
        popup = ColumnSettingsPopup(col, parent=parent)
        qtbot.addWidget(popup)
        popup.show()
        qtbot.waitExposed(popup)
        assert popup._anchor_window is not None
        popup.close()
        assert popup._anchor_window is None

    def test_click_filter_ignores_active_popup(self, qtbot):
        col = RenameColumn(NameSource())
        popup = ColumnSettingsPopup(col)
        qtbot.addWidget(popup)
        popup.show()
        menu = QtWidgets.QMenu(popup)
        menu.addAction('dummy')
        menu.popup(popup.mapToGlobal(QtCore.QPoint(0, 0)))
        filt = popup._click_filter
        event = QtGui.QMouseEvent(
            QtCore.QEvent.MouseButtonPress,
            QtCore.QPointF(-9999, -9999),
            QtCore.QPointF(-9999, -9999),
            Qt.LeftButton, Qt.LeftButton, Qt.NoModifier,
        )
        assert filt.eventFilter(None, event) is False
        menu.close()
