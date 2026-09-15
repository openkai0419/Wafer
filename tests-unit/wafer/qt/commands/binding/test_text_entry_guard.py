import pytest
from PySide6 import QtCore, QtGui, QtWidgets

from wafer.qt.commands.binding.common import TEXT_ENTRY_TYPES, is_text_entry_focused
from wafer.qt.commands.binding.key import shortcutmanager as sm_mod
from wafer.qt.commands.binding.key.shortcutmanager import ShortcutManager


class TestIsTextEntryFocused:
    def test_line_edit_focused(self, qtbot):
        w = QtWidgets.QLineEdit()
        qtbot.addWidget(w)
        w.show()
        w.activateWindow()
        w.setFocus()
        qtbot.waitUntil(lambda: QtWidgets.QApplication.focusWidget() is w)
        assert is_text_entry_focused() is True

    def test_plain_widget_not_text_entry(self, qtbot):
        w = QtWidgets.QPushButton("x")
        qtbot.addWidget(w)
        w.show()
        w.activateWindow()
        w.setFocus()
        qtbot.waitUntil(lambda: QtWidgets.QApplication.focusWidget() is w)
        assert is_text_entry_focused() is False

    def test_text_entry_types_cover_common_inputs(self):
        assert QtWidgets.QLineEdit in TEXT_ENTRY_TYPES
        assert QtWidgets.QPlainTextEdit in TEXT_ENTRY_TYPES
        assert QtWidgets.QTextEdit in TEXT_ENTRY_TYPES


class TestEventFilterTextEntryGuard:
    @pytest.fixture
    def focused_target(self, qtbot):
        prev_mode = ShortcutManager.scope_mode()
        ShortcutManager.set_scope_mode("focus")
        ShortcutManager()
        manager = ShortcutManager._global
        widget = QtWidgets.QWidget()
        qtbot.addWidget(widget)
        widget.show()
        widget.activateWindow()
        widget.setFocus()
        qtbot.waitUntil(lambda: QtWidgets.QApplication.focusWidget() is widget)
        yield manager, widget
        manager.remove_key_listeners(widget)
        ShortcutManager.set_scope_mode(prev_mode)

    def test_consume_listener_receives_key_while_text_entry(self, focused_target, monkeypatch):
        manager, widget = focused_target
        monkeypatch.setattr(sm_mod, "is_text_entry_focused", lambda: True)
        presses = []
        manager.add_key_listener(widget, on_press=presses.append, consume=True)
        event = QtGui.QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_A, QtCore.Qt.NoModifier)
        consumed = manager.eventFilter(widget, event)
        assert presses == [int(QtCore.Qt.Key_A)]
        assert consumed is True

    def test_bound_command_suppressed_while_text_entry(self, focused_target, monkeypatch):
        manager, widget = focused_target
        manager.add_key_listener(widget, on_press=lambda k: None)
        monkeypatch.setattr(manager._state, "payload_for_press", lambda **kw: "PAYLOAD")
        execs = []
        monkeypatch.setattr(manager, "_exec", lambda *args, **kwargs: execs.append(args))

        monkeypatch.setattr(sm_mod, "is_text_entry_focused", lambda: False)
        manager.eventFilter(widget, QtGui.QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_A, QtCore.Qt.NoModifier))
        assert execs

        execs.clear()
        monkeypatch.setattr(sm_mod, "is_text_entry_focused", lambda: True)
        manager.eventFilter(widget, QtGui.QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_B, QtCore.Qt.NoModifier))
        assert not execs

    def test_release_clears_state_when_text_entry_focused_after_press(self, focused_target, monkeypatch):
        manager, widget = focused_target
        manager.add_key_listener(widget, on_press=lambda k: None)

        monkeypatch.setattr(sm_mod, "is_text_entry_focused", lambda: False)
        manager.eventFilter(widget, QtGui.QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_A, QtCore.Qt.NoModifier))
        assert int(QtCore.Qt.Key_A) in manager._state._logical.pressed

        monkeypatch.setattr(sm_mod, "is_text_entry_focused", lambda: True)
        manager.eventFilter(widget, QtGui.QKeyEvent(QtCore.QEvent.KeyRelease, QtCore.Qt.Key_A, QtCore.Qt.NoModifier))
        assert int(QtCore.Qt.Key_A) not in manager._state._logical.pressed
