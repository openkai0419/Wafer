import pytest
from PySide6 import QtWidgets

from source.actions.command.core import CommandMeta
from source.actions.command.payload import CommandPayload
from source.actions.binding.key.sequence import KeySequence
from source.actions.binding.mixins import CommandBindingMixin
from source.actions.bridge import Menu
from source.image_viewer.commands.file_commands import FileCommands


class _BindWidget(QtWidgets.QWidget, CommandBindingMixin):
    def __init__(self, scope: str):
        super().__init__()
        self.init_command_binding(scope)


def _first_row_hotkey(menu: QtWidgets.QMenu) -> str:
    a0 = menu.actions()[0]
    w = a0.defaultWidget() if hasattr(a0, "defaultWidget") else None
    return str(getattr(w, "_hotkey", "") or "") if w is not None else ""


def test_commandmeta_hotkey_is_forbidden():
    with pytest.raises(ValueError):
        CommandMeta(id="x", display="X", hotkey="Ctrl+X")


def test_menu_hotkey_is_resolved_from_bindings(qtbot):
    FileCommands.register()
    w = _BindWidget("*")
    qtbot.addWidget(w)
    w.set_shortcut_bindings({KeySequence(["Ctrl", "C"]): CommandPayload("file.copy", {})})
    m = Menu.session(w).menu(["file.copy"]).build()
    assert _first_row_hotkey(m) == "Ctrl+C"


def test_menu_installs_hotkey_alignment_hook(qtbot):
    FileCommands.register()
    w = _BindWidget("*")
    qtbot.addWidget(w)
    m = Menu.session(w).menu(["file.copy"]).build()
    assert bool(m.property("__hotkey_align_installed__")) is True
