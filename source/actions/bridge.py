from __future__ import annotations

from pathlib import Path

from PySide6 import QtGui, QtWidgets

from .binding.common import WidgetRef
from .binding.manager import BindingManager
from .binding.seed import get_seed_key_bindings, get_seed_mouse_bindings, set_seed_bindings
from .command.core import CommandRegistry
from .command.state import CommandOptionStore


class Kit:
    from .binding.mixins import CommandBindingMixin as UIMixin
    from .command.core import COMMAND_MENU_MARKER as MARKER, CommandMeta as Command, CommandParam as Param
    from .command.menu import RegistryBackedMenu as MenuBase
    from .command.payload import ScopedPayloads as Bind
    from .command.ui import CommandMenuBuilder as CommandBuilder
    from .binding.key.sequence import Key as Key
    from .binding.mouse.mouseeventmanager import MouseActionKey as Mouse


class Settings:
    _instance: "Settings | None" = None
    _configured: bool = False

    def __init__(
        self,
        *,
        mouse_bindings: str | Path,
        key_bindings: str | Path,
        command_options: str | Path,
        key_scope_mode: str | None = None,
        seed_mouse_bindings=None,
        seed_key_bindings=None,
    ):
        self.mouse_bindings = str(mouse_bindings)
        self.key_bindings = str(key_bindings)
        self.command_options = str(command_options)
        self._key_scope_mode = str(key_scope_mode).strip().lower() if key_scope_mode is not None else None
        set_seed_bindings(mouse_bindings=seed_mouse_bindings, key_bindings=seed_key_bindings)
        BindingManager.configure(self.mouse_bindings, self.key_bindings)
        CommandOptionStore.configure(self.command_options)
        if self._key_scope_mode is not None:
            from .binding.key.shortcutmanager import ShortcutManager

            ShortcutManager.set_scope_mode(self._key_scope_mode)

    @classmethod
    def configure(
        cls,
        *,
        mouse_bindings: str | Path,
        key_bindings: str | Path,
        command_options: str | Path,
        key_scope_mode: str | None = None,
        seed_mouse_bindings=None,
        seed_key_bindings=None,
    ) -> "Settings":
        if cls._configured:
            raise RuntimeError("bridge is already configured")
        inst = cls(
            mouse_bindings=mouse_bindings,
            key_bindings=key_bindings,
            command_options=command_options,
            key_scope_mode=key_scope_mode,
            seed_mouse_bindings=seed_mouse_bindings,
            seed_key_bindings=seed_key_bindings,
        )
        cls._instance = inst
        cls._configured = True
        return inst

    @classmethod
    def set_key_scope_mode(cls, mode: str) -> None:
        from .binding.key.shortcutmanager import ShortcutManager

        ShortcutManager.set_scope_mode(mode)
        if cls._instance is not None:
            cls._instance._key_scope_mode = str(mode).strip().lower()

    @classmethod
    def key_scope_mode(cls) -> str:
        from .binding.key.shortcutmanager import ShortcutManager

        return ShortcutManager.scope_mode()

    @classmethod
    def instance(cls) -> "Settings":
        if cls._instance is None:
            raise RuntimeError("bridge is not configured")
        return cls._instance

    @classmethod
    def seed_mouse_bindings(cls):
        return get_seed_mouse_bindings()

    @classmethod
    def seed_key_bindings(cls):
        return get_seed_key_bindings()

    @classmethod
    def activate(cls, *, mouse_bindings=None, key_bindings=None) -> BindingManager:
        return cls.instance()._activate(mouse_bindings=mouse_bindings, key_bindings=key_bindings)

    @classmethod
    def commit(cls) -> None:
        cls.instance()._commit()

    def _activate(self, *, mouse_bindings=None, key_bindings=None) -> BindingManager:
        set_seed_bindings(mouse_bindings=mouse_bindings, key_bindings=key_bindings)
        eff_mouse = mouse_bindings if mouse_bindings is not None else get_seed_mouse_bindings()
        eff_key = key_bindings if key_bindings is not None else get_seed_key_bindings()
        if (eff_mouse is not None or eff_key is not None) and not self._bindings_ok():
            self._set_bindings_from_specs(eff_mouse, eff_key)
            self._save_bindings()
        return BindingManager.activate()

    def _load_bindings(self) -> tuple[bool, bool]:
        from .binding.key.store import KeyBindingStore
        from .binding.mouse.store import MouseBindingStore

        mouse_ok = MouseBindingStore().load_from_file(self.mouse_bindings)
        key_ok = KeyBindingStore().load_from_file(self.key_bindings)
        return mouse_ok, key_ok

    def _bindings_ok(self) -> bool:
        mouse_ok, key_ok = self._load_bindings()
        return mouse_ok and key_ok

    def _save_bindings(self) -> None:
        BindingManager.instance().save()

    def _set_bindings_from_specs(self, mouse_specs=None, key_specs=None) -> None:
        from .binding.key.store import KeyBindingStore
        from .binding.mouse.store import MouseBindingStore

        if mouse_specs is not None:
            MouseBindingStore().set_all(mouse_specs)
        if key_specs is not None:
            KeyBindingStore().set_all(key_specs)

    def _commit(self) -> None:
        from .command.state import ActionGroupStateManager

        BindingManager.instance().save()
        ActionGroupStateManager().commit()
        CommandOptionStore().commit()


class UI:
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

        cmds = list(Command._registry().get_all_commands().keys())
        dlg = ShortcutBindingEditor(ws, cmds, parent=parent)
        dlg.exec()

    @staticmethod
    def set_block_parent(widget):
        from .binding.key.shortcutmanager import ShortcutManager

        widget.setProperty(ShortcutManager.BLOCK_PARENT_SHORTCUTS_PROP, True)
        return widget

    @staticmethod
    def register_widget(name: str, widget: QtWidgets.QWidget) -> QtWidgets.QWidget:
        if not name:
            raise ValueError("name is required")
        if widget is None:
            raise ValueError("widget is required")
        from .binding.widget_registry import WidgetRegistry

        WidgetRegistry.instance().register(str(name), widget)
        return widget


class Command:
    @staticmethod
    def _registry():
        return CommandRegistry()

    @staticmethod
    def execute(command_id: str, *, ctx=None, **kwargs):
        if ctx is None:
            ctx = kwargs.pop("ctx", None)
        if ctx is None:
            ctx = Context.create_context(None, "*", source="bridge")
        return Command._registry().execute(str(command_id), ctx=ctx, **kwargs)

    @staticmethod
    def cycle_action_group(group_name: str):
        return Kit.CommandBuilder().cycle_action_group(str(group_name))

    @staticmethod
    def get_action_group_current(group_name: str):
        return Kit.CommandBuilder().get_action_group_current(str(group_name))

    @staticmethod
    def register_commands(defs) -> None:
        from .command.core import register_command_defs

        register_command_defs(defs)


class Menu:
    @staticmethod
    def _get_builder(parent: QtWidgets.QWidget | None = None, *, seed_ctx=None):
        from .command.ui import MenuBuilder

        return MenuBuilder(parent, seed_ctx=seed_ctx)

    @staticmethod
    def _normalize_menu_items(items) -> list[str]:
        if items is None:
            return []
        if isinstance(items, str):
            s = items.strip()
            return [s] if s else []
        if isinstance(items, (list, tuple)):
            return [str(x) for x in items if x]
        raise TypeError(f"items must be str or list[str], got: {type(items).__name__}")

    @staticmethod
    def build_menu(
        items,
        parent: QtWidgets.QWidget | None = None,
        *,
        seed_ctx=None,
        selection_callback=None,
        allow_options_with_selection: bool = False,
    ):
        b = Menu._get_builder(parent, seed_ctx=seed_ctx)
        return b.build(Menu._normalize_menu_items(items), selection_callback=selection_callback, allow_options_with_selection=allow_options_with_selection)

    def exec_menu(items, ctx=None):
        target, pos = Context.prepare_context_menu(ctx)
        if not target:
            return
        seed = ctx if ctx is not None and hasattr(ctx, "get") else None
        m = Menu.build_menu(items, target, seed_ctx=seed)
        return m.exec(pos)

    def exec_all_roots(ctx=None):
        target, pos = Context.prepare_context_menu(ctx)
        if not target:
            return
        seed = ctx if ctx is not None and hasattr(ctx, "get") else None
        m = Menu.build_all_roots(target, seed_ctx=seed)
        m.exec(pos)

    @staticmethod
    def build_all_roots(
        parent: QtWidgets.QWidget | None = None,
        *,
        seed_ctx=None,
        selection_callback=None,
        allow_options_with_selection: bool = False,
    ):
        b = Menu._get_builder(parent, seed_ctx=seed_ctx)
        return b.build_all_roots(selection_callback=selection_callback, allow_options_with_selection=allow_options_with_selection)

    @staticmethod
    def use_menu(folder: str, parent: QtWidgets.QWidget | None = None, *, seed_ctx=None):
        b = Menu._get_builder(parent, seed_ctx=seed_ctx)
        return b.use(str(folder))


class Context:
    @staticmethod
    def prepare_context_menu(ctx=None):
        active_popup = QtWidgets.QApplication.activePopupWidget()
        if active_popup and active_popup.property(Kit.MARKER):
            active_popup.close()

        seed = ctx if ctx is not None and hasattr(ctx, "get") else None
        pos = seed.get("global_pos") if seed is not None else None
        if pos is None:
            pos = QtGui.QCursor.pos()

        target = seed.get("widget") if seed is not None else None
        if target is None:
            target = QtWidgets.QApplication.widgetAt(pos)
        if target is None:
            return None, None

        while target and not hasattr(target, "binding_scope"):
            target = target.parentWidget()
        if not target:
            return None, None
        return target, pos

    @staticmethod
    def create_context(
        widget=None,
        scope: str | None = None,
        *,
        source: str = "",
        event=None,
        key=None,
        start_pos=None,
        start_global_pos=None,
        extras: dict | None = None,
        seed=None,
    ):
        from .command.context import CommandContext

        return CommandContext.create(
            widget,
            scope,
            source=source,
            event=event,
            key=key,
            start_pos=start_pos,
            start_global_pos=start_global_pos,
            extras=extras,
            seed=seed,
        )
