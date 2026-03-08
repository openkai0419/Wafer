from __future__ import annotations

from pathlib import Path

from PySide6 import QtGui, QtWidgets

from .binding.common import WidgetRef
from .binding.manager import BindingManager
from .binding.presets import get_key_preset, get_mouse_preset, set_presets
from .command.core import CommandRegistry
from .command.menu_session import MenuSession, MenuSpec
from .command.state import CommandOptionStore
from ...utils.logs import AppLogger


class ActionKit:
    from .binding.mixins import CommandBindingMixin as UIMixin
    from .command.core import COMMAND_MENU_MARKER as MENU_MARKER, CommandMeta as Command, CommandParam as Param
    from .command.menu import MenuGroup as MenuBase
    from .command.menu import DragMenuGroup as DragMenuBase
    from .command.payload import ScopedPayloads
    from .command.menu_builder import CommandMenuBuilder
    from .binding.key.sequence import Key as Key
    from .binding.mouse.types import MouseActionKey as Mouse


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
    ):
        self.mouse_bindings = str(mouse_bindings)
        self.key_bindings = str(key_bindings)
        self.command_options = str(command_options)
        self._key_scope_mode = str(key_scope_mode).strip().lower() if key_scope_mode is not None else None
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
    ) -> "Settings":
        if cls._configured:
            raise RuntimeError("bridge is already configured")
        inst = cls(
            mouse_bindings=mouse_bindings,
            key_bindings=key_bindings,
            command_options=command_options,
            key_scope_mode=key_scope_mode,
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
    def mouse_preset(cls) -> str:
        return get_mouse_preset()

    @classmethod
    def key_preset(cls) -> str:
        return get_key_preset()

    @classmethod
    def activate(cls, *, mouse_preset: str | None = None, key_preset: str | None = None) -> BindingManager:
        return cls.instance()._activate(mouse_preset=mouse_preset, key_preset=key_preset)

    @classmethod
    def commit(cls) -> None:
        cls.instance()._commit()

    def _activate(self, *, mouse_preset: str | None = None, key_preset: str | None = None) -> BindingManager:
        set_presets(mouse=mouse_preset, key=key_preset)
        mouse_ok, key_ok = self._load_bindings()
        if not mouse_ok:
            from .binding.mouse.store import MouseBindingStore
            store = MouseBindingStore.instance()
            store._data = store._seed_data()
        if not key_ok:
            from .binding.key.store import KeyBindingStore
            store = KeyBindingStore.instance()
            store._data = store._seed_data()
        return BindingManager.activate()

    def _load_bindings(self) -> tuple[bool, bool]:
        from .binding.key.store import KeyBindingStore
        from .binding.mouse.store import MouseBindingStore

        mouse_ok = MouseBindingStore.instance().load_from_file(self.mouse_bindings)
        key_ok = KeyBindingStore.instance().load_from_file(self.key_bindings)
        return mouse_ok, key_ok

    def _commit(self) -> None:
        from .command.state import ActionGroupStateManager

        BindingManager.instance().save()
        ActionGroupStateManager.instance().commit()
        CommandOptionStore.instance().commit()


class UI:
    @staticmethod
    def collect_bindable_instances() -> list[WidgetRef]:
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
        ws = UI.collect_bindable_instances()
        if not ws:
            return
        from .binding.mouse.editors import MouseBindingEditor

        dlg = MouseBindingEditor(ws, parent=parent)
        dlg.exec()

    @staticmethod
    def open_shortcut_binding_editor(parent: QtWidgets.QWidget | None = None) -> None:
        ws = UI.collect_bindable_instances()
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
    def register_instance(name: str, instance) -> object:
        if not name:
            raise ValueError("name is required")
        if instance is None:
            raise ValueError("instance is required")
        from .binding.instance_registry import InstanceRegistry

        InstanceRegistry.instance().register(str(name), instance)
        return instance


class Command:
    @staticmethod
    def _registry():
        return CommandRegistry.instance()

    @staticmethod
    def cycle_action_group(group_name: str):
        return ActionKit.CommandMenuBuilder.instance().cycle_action_group(str(group_name))

    @staticmethod
    def get_action_group_current(group_name: str):
        return ActionKit.CommandMenuBuilder.instance().get_action_group_current(str(group_name))

    @staticmethod
    def set_action_group_current(group_name: str, command_id: str):
        ActionKit.CommandMenuBuilder.instance().set_action_group_current(str(group_name), str(command_id))

    @staticmethod
    def get_checked(command_id: str) -> bool:
        cmd_class = Command._registry().get_command(str(command_id))
        if cmd_class is None:
            return False
        return ActionKit.CommandMenuBuilder.instance()._get_checked(
            str(command_id),
            cmd_class.meta
        )

    @staticmethod
    def set_checked(command_id: str, state: bool):
        ActionKit.CommandMenuBuilder.instance().set_checked(str(command_id), bool(state))

    @staticmethod
    def register_commands(defs) -> None:
        from .command.core import register_command_defs

        register_command_defs(defs)

    @staticmethod
    def run(command_id: str, args: dict | None = None, extras: dict | None = None):
        from .command.core import validate_command_args

        reg = Command._registry()
        cmd_class = reg.get_command(str(command_id))
        if cmd_class is None:
            raise ValueError(f"Command not found: {command_id}")
        validated = dict(args or {})
        validate_command_args(cmd_class.meta, validated, require_all=True)
        ctx = Context.create_context(None, "*", source="run", extras=extras)
        return reg.execute(str(command_id), ctx=ctx, **validated)

    @staticmethod
    def invoke(command_id: str, extras: dict | None = None, *, ctx=None, parent=None, **kwargs):
        reg = Command._registry()
        cmd_class = reg.get_command(str(command_id))
        if cmd_class is None:
            raise ValueError(f"Command not found: {command_id}")
        stored = CommandOptionStore.instance().get(str(command_id))
        saved = stored.args if isinstance(stored.args, dict) else {}
        args = {p.name: saved.get(p.name, p.default) for p in (cmd_class.meta.params or [])}
        args.update(kwargs)
        missing_required = [
            p for p in (cmd_class.meta.params or [])
            if p.required and not args.get(p.name)
        ]
        if missing_required:
            Command._show_options_for_required(str(command_id), cmd_class, extras, ctx=ctx, parent=parent)
            return None
        if ctx is None:
            ctx = Context.create_context(None, "*", source="invoke", extras=extras)
        return reg.execute(str(command_id), ctx=ctx, **args)

    @staticmethod
    def _show_options_for_required(command_id: str, cmd_class, extras: dict | None, *, ctx=None, parent=None):
        from PySide6 import QtWidgets
        from .command.option_dialog import CommandOptionsDialog
        if parent is None:
            parent = QtWidgets.QApplication.activeWindow()
        reg = Command._registry()

        def _exec(opts):
            exec_ctx = ctx if ctx is not None else Context.create_context(None, "*", source="invoke", extras=extras)
            reg.execute(command_id, ctx=exec_ctx, **opts)

        dialog = CommandOptionsDialog(cmd_class, parent, execute_callback=_exec)
        dialog.exec()

    @staticmethod
    def get_args(command_id: str) -> dict:
        reg = Command._registry()
        cmd_class = reg.get_command(str(command_id))
        if cmd_class is None:
            raise ValueError(f"Command not found: {command_id}")
        stored = CommandOptionStore.instance().get(str(command_id))
        saved = stored.args if isinstance(stored.args, dict) else {}
        return {p.name: saved.get(p.name, p.default) for p in (cmd_class.meta.params or [])}

    @staticmethod
    def set_args(command_id: str, args: dict, *, commit: bool = True) -> None:
        from .command.core import validate_command_args

        reg = Command._registry()
        cmd_class = reg.get_command(str(command_id))
        if cmd_class is None:
            raise ValueError(f"Command not found: {command_id}")
        validate_command_args(cmd_class.meta, args)
        param_names = {p.name for p in (cmd_class.meta.params or [])}
        store = CommandOptionStore.instance()
        current = store.get(str(command_id))
        merged = {k: v for k, v in (current.args or {}).items() if k in param_names}
        merged.update(args)
        store.set(str(command_id), merged)
        if commit:
            store.commit()

class Menu:
    @staticmethod
    def _normalize_menu_items(items) -> list[str]:
        from .command.maker import MenuMaker

        return MenuMaker._normalize_menu_items(items)

    @staticmethod
    def session(
        parent: QtWidgets.QWidget | None = None,
        *,
        seed_ctx=None,
        maker=None,
        pos=None,
    ) -> "MenuSession":
        return MenuSession(parent, seed_ctx=seed_ctx, maker=maker, pos=pos)

    @staticmethod
    def from_context(ctx=None, *, maker=None) -> "MenuSession | None":
        target, pos = Context.prepare_context_menu(ctx)
        if not target:
            return None
        seed = ctx if ctx is not None and hasattr(ctx, "get") else None
        return Menu.session(target, seed_ctx=seed, maker=maker, pos=pos)

    @staticmethod
    def exec_menu(prefix: str, ctx) -> None:
        s = Menu.from_context(ctx)
        if s is None:
            return
        spec = s.from_folder(prefix)
        if spec is None:
            return
        spec.exec()

    @staticmethod
    def exec_all_roots(ctx) -> None:
        s = Menu.from_context(ctx)
        if s is None:
            return
        spec = s.all_roots()
        if spec is None:
            return
        spec.exec()
    
class Context:
    @staticmethod
    def prepare_context_menu(ctx=None):
        active_popup = QtWidgets.QApplication.activePopupWidget()
        if active_popup and active_popup.property(ActionKit.MENU_MARKER):
            active_popup.close()

        seed = ctx if ctx is not None and hasattr(ctx, "get") else None
        pos = seed.get("global_pos") if seed is not None else None
        if pos is None:
            pos = QtGui.QCursor.pos()

        target = (seed._widget if hasattr(seed, "_widget") else None) if seed is not None else None
        if target is None:
            target = QtWidgets.QApplication.widgetAt(pos)
        if target is None:
            return None, None

        while target and not hasattr(target, "binding_scope"):
            target = target.parentWidget()
        if not target:
            if seed is not None:
                w = seed._widget if hasattr(seed, "_widget") else None
                if w is not None:
                    AppLogger.warning(f"context menu target has no binding_scope: {type(w).__name__}")
            return None, None
        return target, pos

    @staticmethod
    def create_context(
        widget=None,
        scope: str | None = None,
        *,
        source: str = "",
        event=None,
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
            start_pos=start_pos,
            start_global_pos=start_global_pos,
            extras=extras,
            seed=seed,
        )

    @staticmethod
    def create_menu_context(widget=None, scope: str | None = None, *, pos=None, global_pos=None, extras: dict | None = None, seed=None):
        ctx = Context.create_context(widget, scope, source="menu", extras=extras, seed=seed)
        if pos is not None:
            ctx.pos = pos
        if global_pos is not None:
            ctx.global_pos = global_pos
        if widget is not None:
            ctx._widget = widget
        return ctx
