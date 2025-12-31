from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6 import QtWidgets

from .binding.manager import BindingManager
from .command.state import CommandOptionStore


@dataclass(frozen=True, slots=True)
class WidgetRef:
    name: str
    widget: QtWidgets.QWidget


def get_builder(parent: QtWidgets.QWidget | None = None, *, seed_ctx=None):
    from .command.ui import MenuBuilder
    return MenuBuilder(parent, seed_ctx=seed_ctx)


def register_menus(menu_classes) -> None:
    from .command.menu import register_menu_classes

    register_menu_classes(menu_classes)


def collect_bindable_widgets() -> list["WidgetRef"]:
    out: list[WidgetRef] = []
    for tl in QtWidgets.QApplication.topLevelWidgets():
        for w in tl.findChildren(QtWidgets.QWidget):
            if not hasattr(w, "set_mouse_bindings"):
                continue
            name = getattr(w, "name", "") or None
            if name:
                out.append(WidgetRef(name, w))
    return out


def open_mouse_binding_editor(parent: QtWidgets.QWidget | None = None) -> None:
    ws = collect_bindable_widgets()
    if not ws:
        return
    from .binding.mouse.editors import MouseBindingEditor

    dlg = MouseBindingEditor(ws, parent=parent)
    dlg.exec()


def open_shortcut_binding_editor(parent: QtWidgets.QWidget | None = None) -> None:
    ws = collect_bindable_widgets()
    if not ws:
        return
    from .command.core import CommandRegistry
    from .binding.key.editors import ShortcutBindingEditor

    cmds = list(CommandRegistry().get_all_commands().keys())
    dlg = ShortcutBindingEditor(ws, cmds, parent=parent)
    dlg.exec()


class PrototypeBootstrap:
    def __init__(
        self,
        *,
        mouse_bindings: str | Path,
        key_bindings: str | Path,
        command_options: str | Path,
    ):
        self._mouse_bindings = str(mouse_bindings)
        self._key_bindings = str(key_bindings)
        self._command_options = str(command_options)
        BindingManager.configure(self._mouse_bindings, self._key_bindings)
        CommandOptionStore.configure(self._command_options)

    def activate(self) -> BindingManager:
        return BindingManager.activate()

    def set_bindings_from_specs(self, mouse_specs=None, key_specs=None) -> None:
        from .binding.mouse.store import MouseBindingStore
        from .binding.key.store import KeyBindingStore

        if mouse_specs is not None:
            MouseBindingStore().set_all_from_specs(mouse_specs)
        if key_specs is not None:
            KeyBindingStore().set_all_from_specs(key_specs)

    def load_bindings(self) -> tuple[bool, bool]:
        from .binding.mouse.store import MouseBindingStore
        from .binding.key.store import KeyBindingStore

        mouse_ok = MouseBindingStore().load_from_file(self._mouse_bindings)
        key_ok = KeyBindingStore().load_from_file(self._key_bindings)
        return mouse_ok, key_ok

    def bindings_ok(self) -> bool:
        mouse_ok, key_ok = self.load_bindings()
        return mouse_ok and key_ok

    def save_bindings(self) -> None:
        BindingManager.instance().save()


_BOOTSTRAP: PrototypeBootstrap | None = None


def setup(*, mouse_bindings: str | Path, key_bindings: str | Path, command_options: str | Path) -> PrototypeBootstrap:
    global _BOOTSTRAP
    _BOOTSTRAP = PrototypeBootstrap(
        mouse_bindings=mouse_bindings,
        key_bindings=key_bindings,
        command_options=command_options,
    )
    return _BOOTSTRAP


def activate(*, mouse_bindings=None, key_bindings=None) -> BindingManager:
    if _BOOTSTRAP is None:
        raise RuntimeError("facade is not configured")
    if (mouse_bindings is not None or key_bindings is not None) and not _BOOTSTRAP.bindings_ok():
        _BOOTSTRAP.set_bindings_from_specs(mouse_bindings, key_bindings)
        _BOOTSTRAP.save_bindings()
    return _BOOTSTRAP.activate()


def bindings_ok() -> bool:
    if _BOOTSTRAP is None:
        raise RuntimeError("facade is not configured")
    return _BOOTSTRAP.bindings_ok()


def load_bindings() -> tuple[bool, bool]:
    if _BOOTSTRAP is None:
        raise RuntimeError("facade is not configured")
    return _BOOTSTRAP.load_bindings()


def save_bindings() -> None:
    if _BOOTSTRAP is None:
        raise RuntimeError("facade is not configured")
    _BOOTSTRAP.save_bindings()
