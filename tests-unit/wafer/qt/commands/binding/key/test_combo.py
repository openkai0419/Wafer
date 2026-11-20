from PySide6 import QtCore

from wafer.qt.commands.binding.key.combo import ComboParser
from wafer.qt.commands.binding.key.runtime import KeyNameResolver
from wafer.qt.commands.binding.key.sequence import KeySequence


def _parser():
    return ComboParser(KeyNameResolver())


def test_from_sequence_resolves_a_symbol_key():
    combo = _parser().from_sequence(KeySequence(["Control", "Minus"]))
    assert combo == (int(QtCore.Qt.Key.Key_Control), int(QtCore.Qt.Key.Key_Minus))


def test_from_sequence_drops_the_whole_binding_when_a_name_is_unknown():
    assert _parser().from_sequence(KeySequence(["Control", "-"])) == ()
    assert _parser().from_sequence(KeySequence(["-"])) == ()


def test_from_sequence_accepts_aliases():
    combo = _parser().from_sequence(KeySequence(["Ctrl", "Del"]))
    assert combo == (int(QtCore.Qt.Key.Key_Control), int(QtCore.Qt.Key.Key_Delete))
