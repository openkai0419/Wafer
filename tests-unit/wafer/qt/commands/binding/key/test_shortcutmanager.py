import pytest
from PySide6 import QtCore, QtGui, QtWidgets

from wafer.qt.commands.binding.key import shortcutmanager as sm_mod
from wafer.qt.commands.binding.key.sequence import KeySequence
from wafer.qt.commands.binding.key.shortcutmanager import ShortcutManager
from wafer.qt.commands.command.payload import CommandPayload


@pytest.fixture
def bound_widget(qtbot, monkeypatch):
    prev_mode = ShortcutManager.scope_mode()
    ShortcutManager.set_scope_mode("focus")
    ShortcutManager()
    manager = ShortcutManager._global
    window = QtWidgets.QWidget()
    qtbot.addWidget(window)
    widget = QtWidgets.QWidget(window)
    widget.setFocusPolicy(QtCore.Qt.StrongFocus)
    other = QtWidgets.QLabel("toast", window)
    window.show()
    window.activateWindow()
    widget.setFocus()
    qtbot.waitUntil(lambda: QtWidgets.QApplication.focusWidget() is widget)
    manager.set_bindings(widget, {KeySequence(["K"]): CommandPayload("test.k", {})})
    manager._reset_states()
    monkeypatch.setattr(sm_mod, "is_text_entry_focused", lambda: False)
    runs = []
    monkeypatch.setattr(manager, "_exec", lambda wid, payload, event=None: runs.append(payload.id))
    yield manager, window, widget, other, runs
    manager._keymap.pop(id(widget), None)
    manager._widget_refs.pop(id(widget), None)
    manager._invalidate_targets_cache()
    manager._reset_states()
    ShortcutManager.set_scope_mode(prev_mode)


def _press_release(manager, widget, between=None):
    manager.eventFilter(widget, QtGui.QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_K, QtCore.Qt.NoModifier))
    if between is not None:
        between()
    manager.eventFilter(widget, QtGui.QKeyEvent(QtCore.QEvent.KeyRelease, QtCore.Qt.Key_K, QtCore.Qt.NoModifier))


def test_single_key_fires_on_release(bound_widget):
    manager, _, widget, _, runs = bound_widget
    _press_release(manager, widget)
    assert runs == ["test.k"]


def test_an_unrelated_widget_hiding_keeps_the_pressed_key(bound_widget):
    manager, _, widget, other, runs = bound_widget
    _press_release(manager, widget, lambda: manager.eventFilter(other, QtCore.QEvent(QtCore.QEvent.Hide)))
    assert runs == ["test.k"]


def test_the_binding_window_hiding_drops_the_pressed_key(bound_widget):
    manager, window, widget, _, runs = bound_widget
    _press_release(manager, widget, lambda: manager.eventFilter(window, QtCore.QEvent(QtCore.QEvent.Hide)))
    assert runs == []
