from PySide6 import QtCore

from wafer.qt.commands.binding.key.runtime import KeyNameResolver


def test_every_bindable_key_round_trips_through_its_saved_name(qapp):
    r = KeyNameResolver()
    keys = [k for k in r._allowed_keys if k != QtCore.Qt.Key.Key_Enter]
    lost = [QtCore.Qt.Key(k).name for k in keys if r.to_key_code(r.key_name(k)) != k]
    assert lost == []


def test_symbol_keys_are_saved_by_name_and_shown_as_symbols(qapp):
    r = KeyNameResolver()
    assert r.key_name(QtCore.Qt.Key.Key_Minus) == "Minus"
    assert r.key_name(QtCore.Qt.Key.Key_Plus) == "Plus"
    assert r.key_name(QtCore.Qt.Key.Key_Minus, pretty=True) == "-"
    assert r.key_name(QtCore.Qt.Key.Key_Plus, pretty=True) == "+"


def test_named_keys_keep_their_existing_saved_spelling(qapp):
    r = KeyNameResolver()
    assert r.key_name(QtCore.Qt.Key.Key_Delete) == "Del"
    assert r.key_name(QtCore.Qt.Key.Key_Control) == "Control"
    assert r.key_name(QtCore.Qt.Key.Key_Control, pretty=True) == "Ctrl"
