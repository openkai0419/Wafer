from __future__ import annotations

from pathlib import Path

from PySide6 import QtWidgets

from .binding.common import WidgetRef
from .binding.manager import BindingManager
from .command.state import CommandOptionStore

class Classes:
    from .binding.mixins import CommandBindingMixin as UIMixin
    from .command.payload import ScopedPayloads as BindPayloads
    from .command.core import COMMAND_MENU_MARKER as MARKER, CommandMeta as Command, CommandParam as Param
    from .command.menu import RegistryBackedMenu as MenuBase
    from .command.ui import CommandMenuBuilder as CommandBuilder

class Settings:
    _instance: "Settings | None" = None
    _configured: bool = False

    def __init__(
        self,
        *,
        mouse_bindings: str | Path,
        key_bindings: str | Path,
        command_options: str | Path,
        seed_mouse_specs=None,
        seed_key_specs=None,
    ):
        self.mouse_bindings = str(mouse_bindings)
        self.key_bindings = str(key_bindings)
        self.command_options = str(command_options)
        self._seed_mouse_specs = seed_mouse_specs
        self._seed_key_specs = seed_key_specs
        BindingManager.configure(self.mouse_bindings, self.key_bindings)
        CommandOptionStore.configure(self.command_options)

    @classmethod
    def configure(
        cls,
        *,
        mouse_bindings: str | Path,
        key_bindings: str | Path,
        command_options: str | Path,
        seed_mouse_specs=None,
        seed_key_specs=None,
    ) -> "Settings":
        if cls._configured:
            raise RuntimeError("facade is already configured")
        inst = cls(
            mouse_bindings=mouse_bindings,
            key_bindings=key_bindings,
            command_options=command_options,
            seed_mouse_specs=seed_mouse_specs,
            seed_key_specs=seed_key_specs,
        )
        cls._instance = inst
        cls._configured = True
        return inst

    @classmethod
    def instance(cls) -> "Settings":
        if cls._instance is None:
            raise RuntimeError("facade is not configured")
        return cls._instance

    @classmethod
    def seed_mouse_specs(cls):
        return cls.instance()._seed_mouse_specs

    @classmethod
    def seed_key_specs(cls):
        return cls.instance()._seed_key_specs

    @classmethod
    def register_menus(cls, menu_classes) -> None:
        from .command.menu import register_menu_classes

        register_menu_classes(menu_classes)

    @classmethod
    def activate(cls, *, mouse_bindings=None, key_bindings=None) -> BindingManager:
        return cls.instance()._activate(mouse_bindings=mouse_bindings, key_bindings=key_bindings)

    @classmethod
    def commit(cls) -> None:
        cls.instance()._commit()

    def _activate(self, *, mouse_bindings=None, key_bindings=None) -> BindingManager:
        if mouse_bindings is not None:
            self._seed_mouse_specs = mouse_bindings
        if key_bindings is not None:
            self._seed_key_specs = key_bindings
        eff_mouse = mouse_bindings if mouse_bindings is not None else self._seed_mouse_specs
        eff_key = key_bindings if key_bindings is not None else self._seed_key_specs
        if (eff_mouse is not None or eff_key is not None) and not self._bindings_ok():
            self._set_bindings_from_specs(eff_mouse, eff_key)
            self._save_bindings()
        return BindingManager.activate()

    def _load_bindings(self) -> tuple[bool, bool]:
        from .binding.mouse.store import MouseBindingStore
        from .binding.key.store import KeyBindingStore

        mouse_ok = MouseBindingStore().load_from_file(self.mouse_bindings)
        key_ok = KeyBindingStore().load_from_file(self.key_bindings)
        return mouse_ok, key_ok

    def _bindings_ok(self) -> bool:
        mouse_ok, key_ok = self._load_bindings()
        return mouse_ok and key_ok

    def _save_bindings(self) -> None:
        BindingManager.instance().save()

    def _set_bindings_from_specs(self, mouse_specs=None, key_specs=None) -> None:
        from .binding.mouse.store import MouseBindingStore
        from .binding.key.store import KeyBindingStore

        if mouse_specs is not None:
            MouseBindingStore().set_all_from_specs(mouse_specs)
        if key_specs is not None:
            KeyBindingStore().set_all_from_specs(key_specs)

    def _commit(self) -> None:
        from .command.state import ActionGroupStateManager

        BindingManager.instance().save()
        ActionGroupStateManager().commit()
        CommandOptionStore().commit()


class UI:
    @staticmethod
    def get_builder(parent: QtWidgets.QWidget | None = None, *, seed_ctx=None):
        from .command.ui import MenuBuilder

        return MenuBuilder(parent, seed_ctx=seed_ctx)

    @staticmethod
    def collect_bindable_widgets() -> list[WidgetRef]:
        out: list[WidgetRef] = []
        for tl in QtWidgets.QApplication.topLevelWidgets():
            for w in tl.findChildren(QtWidgets.QWidget):
                if not hasattr(w, "set_mouse_bindings"):
                    continue
                name = getattr(w, "name", "") or None
                if name:
                    out.append(WidgetRef(name, w))
        return out

    @staticmethod
    def open_mouse_binding_editor(parent: QtWidgets.QWidget | None = None) -> None:
        ws = UI.collect_bindable_widgets()
        if not ws:
            return
        from .binding.mouse.editors import MouseBindingEditor

        dlg = MouseBindingEditor(ws, parent=parent)
        dlg.exec()

    @staticmethod
    def open_shortcut_binding_editor(parent: QtWidgets.QWidget | None = None) -> None:
        ws = UI.collect_bindable_widgets()
        if not ws:
            return
        from .binding.key.editors import ShortcutBindingEditor
        from .command.core import CommandRegistry

        cmds = list(CommandRegistry().get_all_commands().keys())
        dlg = ShortcutBindingEditor(ws, cmds, parent=parent)
        dlg.exec()
