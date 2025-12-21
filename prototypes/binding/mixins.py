from __future__ import annotations
from typing import Any, Dict, Optional
from PySide6 import QtWidgets
from source.common.profiling import profiler
from ..command.core import CommandRegistry
from ..utils import CommandPayload
from .mouse.mouseeventmanager import MouseEventManager, MouseEventDispatcher, MouseActionKey, ClickType
from .key.shortcutmanager import ShortcutManager
from .mouse.store import MouseBindingStore
from .manager import BindingManager


class CommandBindingMixin:
    def init_command_binding(self, name: str, enable_drops: bool = False):
        if not name:
            raise ValueError("name is required")
        self.name = name
        self._registry = CommandRegistry()
        self._mouse_manager = MouseEventManager()
        self._mouse_manager.set_registry(self._registry)
        self._mouse_dispatcher = MouseEventDispatcher(self, self._mouse_manager, enable_drag=enable_drops)
        self._mouse_bindings: Dict[MouseActionKey, CommandPayload] = {}
        self._store = MouseBindingStore()
        self._shortcut_manager = ShortcutManager()
        self._mouse_manager.set_resolver(self._resolve_fallback)
        BindingManager.instance().register(self)

    def set_binding_scope(self, name: str):
        if not name:
            raise ValueError("name is required")
        self.name = name

    def binding_scope(self) -> str:
        return self.name

    def set_mouse_bindings(self, bindings: Dict[MouseActionKey, CommandPayload]):
        self._mouse_bindings = {}
        self._mouse_manager.clear()
        for k, cmd in bindings.items():
            if not isinstance(cmd, CommandPayload):
                raise TypeError("Mouse binding payload must be CommandPayload")
            self._mouse_bindings[k] = cmd
            self._mouse_manager.bind(k, lambda e=None, c=cmd, kk=k: self._execute_payload(c, event=e, key=kk, source="mouse"))
        self._mouse_manager.set_resolver(self._resolve_fallback)

    def get_mouse_bindings(self) -> Dict[MouseActionKey, CommandPayload]:
        return dict(self._mouse_bindings)

    def _resolve_fallback(self, key: MouseActionKey, event=None):
        cmd = self._store.resolve(self.binding_scope(), key)
        if not cmd and key.click_type == ClickType.DOUBLE:
            skey = MouseActionKey(key.button, ClickType.SINGLE, key.held_buttons)
            cmd = self._store.resolve(self.binding_scope(), skey)
            if isinstance(cmd, CommandPayload):
                self._execute_payload(cmd, event=event, key=skey, source="mouseFallback")
                return True
            return False
        if isinstance(cmd, CommandPayload):
            self._execute_payload(cmd, event=event, key=key, source="mouseFallback")
            return True
        return False

    def set_shortcut_bindings(self, bindings: Dict[str, CommandPayload]):
        self._shortcut_manager.set_bindings(self, bindings)

    def get_shortcut_bindings(self) -> Dict[str, CommandPayload]:
        return self._shortcut_manager.get_bindings(self)

    def set_physical_shortcut_bindings(self, bindings: Dict[str, CommandPayload]):
        self._shortcut_manager.set_physical_bindings(self, bindings)

    def set_key_bindings(self, bindings: Dict[tuple, CommandPayload]):
        self._shortcut_manager.set_key_bindings(self, bindings)

    def exec_command(self, cmd: Any, event=None, key: Optional[MouseActionKey]=None, source: Optional[str]=None, extra: Optional[Dict[str, Any]]=None):
        self._execute_payload(cmd, event=event, key=key, source=source, extra=extra)

    def provider(self, cmd: Any, event=None, key: Optional[MouseActionKey]=None, source: Optional[str]=None) -> Dict[str, Any]:
        return {}

    @profiler.profile
    def _execute_payload(self, cmd: CommandPayload, event=None, key: Optional[MouseActionKey]=None, source: Optional[str]=None, extra: Optional[Dict[str, Any]]=None):
        if not isinstance(cmd, CommandPayload):
            raise TypeError("Command payload must be CommandPayload")
        ctx = self._build_execution_context(cmd, event, key, source, extra)
        args = self._merge_arguments(cmd, ctx, source)
        if event is not None:
            args['event'] = event
        if key is not None:
            args['key'] = key
        self._registry.execute(str(cmd.id), **args)
        self._update_checkable_state(cmd, args)

    def _build_execution_context(self, cmd: CommandPayload, event=None, key: Optional[MouseActionKey]=None, source: Optional[str]=None, extra: Optional[Dict[str, Any]]=None) -> Dict[str, Any]:
        ctx: Dict[str, Any] = {}
        try:
            ctx = self.provider(cmd, event=event, key=key, source=source) or {}
        except Exception:
            pass
        if isinstance(extra, dict):
            try:
                ctx.update(extra)
            except Exception:
                pass
        return ctx

    def _merge_arguments(self, cmd: CommandPayload, ctx: Dict[str, Any], source: Optional[str]) -> Dict[str, Any]:
        from ..command.state import CommandOptionStore
        store = CommandOptionStore()
        stored_payload = store.get(cmd.id)
        args = dict(cmd.args or {}) or dict(stored_payload.args or {})
        if ctx:
            args.update(ctx)
        cls = self._registry.get_command(str(cmd.id))
        if cls and getattr(getattr(cls, "meta", None), "checkable", False):
            meta = getattr(cls, "meta", None)
            cur_checked = bool(dict(getattr(stored_payload, "args", {}) or {}).get("checked", getattr(meta, "default_checked", False)))
            if isinstance(source, str) and source.startswith("mouse"):
                new_checked = not cur_checked
            else:
                new_checked = bool(args.get("checked")) if "checked" in args else not cur_checked
            args["checked"] = new_checked
        return args

    def _update_checkable_state(self, cmd: CommandPayload, args: Dict[str, Any]):
        try:
            cls = self._registry.get_command(str(cmd.id))
            if cls and getattr(getattr(cls, "meta", None), "checkable", False):
                from ..command.state import CommandOptionStore
                store = CommandOptionStore()
                stored_payload = store.get(cmd.id)
                opts = dict(getattr(stored_payload, "args", {}) or {})
                opts["checked"] = bool(args.get("checked", opts.get("checked", False)))
                store.set(cmd.id, opts)
        except Exception:
            pass
