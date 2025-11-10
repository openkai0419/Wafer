from __future__ import annotations
from typing import Any, Dict, Optional
import json
from PySide6 import QtWidgets
from ..command.core import CommandRegistry
from ..utils import to_payload_json, is_json_text, show_error
from .mouse.mouseeventmanager import MouseEventManager, MouseEventDispatcher, MouseActionKey
from .key.shortcutmanager import ShortcutManager
from .mouse.store import MouseBindingStore
from .manager import BindingManager


class CommandBindingMixin:
    def init_command_binding(self, name: str):
        if not name:
            raise ValueError("name is required")
        self.name = name
        self._registry = CommandRegistry()
        self._mouse_manager = MouseEventManager()
        self._mouse_dispatcher = MouseEventDispatcher(self, self._mouse_manager)
        self._mouse_bindings: Dict[MouseActionKey, str] = {}
        self._store = MouseBindingStore()
        self._shortcut_manager = ShortcutManager()
        self._mouse_manager.set_resolver(self._resolve_fallback)
        try:
            BindingManager.instance().register(self)
        except Exception:
            pass

    def set_binding_scope(self, name: str):
        if not name:
            raise ValueError("name is required")
        self.name = name

    def binding_scope(self) -> str:
        return self.name

    def set_mouse_bindings(self, bindings: Dict[MouseActionKey, object]):
        self._mouse_bindings = {}
        self._mouse_manager.clear()
        for k, cmd in bindings.items():
            if isinstance(cmd, str) and is_json_text(cmd):
                s = cmd.strip()
            elif isinstance(cmd, dict) and "id" in cmd:
                s = to_payload_json(cmd)
            else:
                s = str(cmd)
            self._mouse_bindings[k] = s
            self._mouse_manager.bind(k, lambda e=None, c=s, kk=k: self._exec(c, event=e, key=kk, source="mouse"))
        self._mouse_manager.set_resolver(self._resolve_fallback)

    def get_mouse_bindings(self) -> Dict[MouseActionKey, str]:
        return dict(self._mouse_bindings)

    def _resolve_fallback(self, key: MouseActionKey, event=None):
        cmd = self._store.resolve(self.binding_scope(), key)
        if not cmd:
            return
        if isinstance(cmd, str) and is_json_text(cmd):
            self._exec(cmd, event=event, key=key, source="mouseFallback")
            return
        if isinstance(cmd, dict) and "id" in cmd:
            try:
                self._exec(to_payload_json(cmd), event=event, key=key, source="mouseFallback")
            except Exception:
                show_error(self, "Failed to resolve command")
            return
        if isinstance(cmd, str):
            self._exec(cmd, event=event, key=key, source="mouseFallback")

    def set_shortcut_bindings(self, bindings: Dict[str, str]):
        self._shortcut_manager.set_bindings(self, bindings)

    def get_shortcut_bindings(self) -> Dict[str, str]:
        return self._shortcut_manager.get_bindings(self)

    def exec_command(self, cmd: Any, event=None, key: Optional[MouseActionKey]=None, source: Optional[str]=None, extra: Optional[Dict[str, Any]]=None):
        self._exec(cmd, event=event, key=key, source=source, extra=extra)

    def provider(self, cmd: Any, event=None, key: Optional[MouseActionKey]=None, source: Optional[str]=None) -> Dict[str, Any]:
        return {}

    def _exec(self, cmd: Any, event=None, key: Optional[MouseActionKey]=None, source: Optional[str]=None, extra: Optional[Dict[str, Any]]=None):
        try:
            ctx = {}
            try:
                ctx = self.provider(cmd, event=event, key=key, source=source) or {}
            except Exception:
                ctx = {}
            if isinstance(extra, dict):
                try:
                    ctx.update(extra)
                except Exception:
                    pass
            if not cmd:
                return
            if isinstance(cmd, str) and is_json_text(cmd):
                try:
                    d = json.loads(cmd)
                except Exception:
                    d = None
                if isinstance(d, dict) and "id" in d and isinstance(d.get("args"), dict) and not d.get("args"):
                    from ..command.state import CommandOptionStore
                    try:
                        stored = CommandOptionStore().get(d.get("id"))
                        self._registry.execute_payload(stored, ctx)
                        return
                    except Exception:
                        pass
                self._registry.execute_payload(cmd, ctx)
            elif isinstance(cmd, dict) and "id" in cmd:
                self._registry.execute_payload(cmd, ctx)
            elif isinstance(cmd, str):
                from ..command.state import CommandOptionStore
                try:
                    payload = CommandOptionStore().get(cmd)
                except Exception:
                    payload = {"id": cmd, "args": {}}
                self._registry.execute_payload(payload, ctx)
        except Exception as e:
            show_error(self, str(e))
            raise
