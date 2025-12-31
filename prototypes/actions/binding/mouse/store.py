from __future__ import annotations
from typing import Any, Dict, Optional, List
from pathlib import Path
from source.common.profiling import profiler
from source.common.jsons import read_json_file, write_json_file
from source.common.errors import show_warning
from ...command.payload import CommandPayload, normalize_scoped_payloads
from .mouseeventmanager import MouseActionKey, ModifierKey

class MouseBindingStore:
    _instance: Optional["MouseBindingStore"] = None
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._map = {}
        return cls._instance
    def get_all(self) -> Dict[MouseActionKey, Dict[str, CommandPayload]]:
        return {k: dict(v) for k, v in self._map.items()}

    @staticmethod
    def normalize_specs(data: Dict[Any, Any]) -> Dict[MouseActionKey, Dict[str, CommandPayload]]:
        nm: Dict[MouseActionKey, Dict[str, CommandPayload]] = {}
        for k, scopes in (data or {}).items():
            key = k if isinstance(k, MouseActionKey) else MouseActionKey.from_spec(k)
            dst = normalize_scoped_payloads(scopes)
            if dst:
                nm[key] = dst
        return nm
    def set_all(self, data: Dict[Any, Any]):
        try:
            self._map = self.normalize_specs(data)
        except Exception as e:
            raise TypeError("MouseBindingStore requires CommandPayload") from e

    def set_all_from_specs(self, data: Dict[Any, Any]):
        self.set_all(data)
    def set_binding(self, key: MouseActionKey, scope: str, command: Optional[Any]):
        if not scope:
            scope = "*"
        if not command:
            if key in self._map and scope in self._map[key]:
                d = self._map[key]
                d.pop(scope, None)
                if not d:
                    self._map.pop(key, None)
            return
        try:
            norm = CommandPayload.from_any(command)
        except Exception as e:
            raise TypeError("MouseBindingStore.set_binding requires CommandPayload") from e
        d = self._map.setdefault(key, {})
        d[scope] = norm
    @profiler.profile
    def resolve(self, widget: str, key: MouseActionKey) -> Optional[CommandPayload]:
        d = self._map.get(key)
        if not d:
            return None
        if widget in d:
            return d.get(widget)
        return d.get("*")
    def to_serializable(self) -> List[Dict[str, Any]]:
        r: List[Dict[str, Any]] = []
        for k, scopes in self._map.items():
            try:
                ser_scopes: Dict[str, Any] = {}
                for sc, payload in scopes.items():
                    ser_scopes[sc] = payload.to_dict()
                entry = {
                    "button": k.button.name,
                    "click": k.click_type.name,
                    "held": [b.name for b in sorted(list(k.held_buttons), key=lambda x: x.name)],
                    "modifiers": [m.name for m in sorted(list(getattr(k, "modifiers", frozenset())), key=lambda x: x.name)],
                    "scopes": ser_scopes,
                }
                r.append(entry)
            except Exception as e:
                show_warning(None, "MouseBindingStore.to_serializable failed", exc=e)
        return r

    def _parse_modifiers(self, raw) -> List[ModifierKey]:
        if raw is None:
            return []
        parts: List[str] = []
        if isinstance(raw, str):
            s = raw.replace("|", "+").replace(" ", "+")
            parts = [p for p in s.split("+") if p]
        elif isinstance(raw, (list, tuple)):
            parts = [str(p) for p in raw if p]
        else:
            return []
        out: List[ModifierKey] = []
        for p in parts:
            u = str(p).strip().upper()
            if u in ("CTRL", "CONTROL"):
                out.append(ModifierKey.CTRL)
            elif u in ("SHIFT",):
                out.append(ModifierKey.SHIFT)
            elif u in ("ALT", "OPTION"):
                out.append(ModifierKey.ALT)
            elif u in ("META", "CMD", "COMMAND", "WIN", "WINDOWS", "SUPER"):
                out.append(ModifierKey.META)
        return out
    def load_serializable(self, data: List[Dict[str, Any]], on_error: Optional[callable] = None):
        from .mouseeventmanager import MouseButton, ClickType
        nm: Dict[MouseActionKey, Dict[str, CommandPayload]] = {}
        for e in data:
            try:
                btn = MouseButton[e.get("button")] if isinstance(e.get("button"), str) else None
                clk = ClickType[e.get("click")] if isinstance(e.get("click"), str) else None
                held_raw = e.get("held") or []
                held = []
                for h in held_raw:
                    try:
                        held.append(MouseButton[h])
                    except Exception:
                        if callable(on_error):
                            try:
                                on_error("invalid held button", None)
                            except Exception:
                                show_warning(None, "MouseBindingStore on_error failed: invalid held button")
                        else:
                            show_warning(None, "invalid held button")
                scopes = e.get("scopes") or {}
                if not btn or not clk or not isinstance(scopes, dict):
                    continue
                mods = self._parse_modifiers(e.get("modifiers"))
                key = MouseActionKey(btn, clk, tuple(held), tuple(mods))
                nm[key] = {}
                for sc, cmd in scopes.items():
                    if cmd is None:
                        continue
                    if isinstance(cmd, str):
                        try:
                            nm[key][sc] = CommandPayload.from_json(cmd)
                        except Exception as ex:
                            if callable(on_error):
                                try:
                                    on_error("invalid payload json", ex)
                                except Exception:
                                    show_warning(None, "MouseBindingStore on_error failed: invalid payload json", exc=ex)
                            else:
                                show_warning(None, "invalid payload json", exc=ex)
                    elif isinstance(cmd, dict):
                        try:
                            nm[key][sc] = CommandPayload.from_dict(cmd)
                        except Exception as ex:
                            if callable(on_error):
                                try:
                                    on_error("invalid payload dict", ex)
                                except Exception:
                                    show_warning(None, "MouseBindingStore on_error failed: invalid payload dict", exc=ex)
                            else:
                                show_warning(None, "invalid payload dict", exc=ex)
                    else:
                        if callable(on_error):
                            try:
                                on_error("unsupported payload type", None)
                            except Exception:
                                show_warning(None, "MouseBindingStore on_error failed: unsupported payload type")
                        else:
                            show_warning(None, "unsupported payload type")
            except Exception as ex:
                if callable(on_error):
                    try:
                        on_error("entry parse error", ex)
                    except Exception:
                        show_warning(None, "MouseBindingStore on_error failed: entry parse error", exc=ex)
                else:
                    show_warning(None, "entry parse error", exc=ex)
        self._map = nm
    def save_to_file(self, path: str):
        try:
            p = Path(path)
            if p.parent:
                p.parent.mkdir(parents=True, exist_ok=True)
            write_json_file(p, self.to_serializable(), indent=2, ensure_ascii=False)
        except Exception as e:
            show_warning(None, f"MouseBindingStore.save_to_file failed: {path}", exc=e)
    def load_from_file(self, path: str):
        try:
            data = read_json_file(Path(path), None)
            if isinstance(data, list):
                self.load_serializable(data)
                return True
            return False
        except Exception as e:
            show_warning(None, f"MouseBindingStore.load_from_file failed: {path}", exc=e)
            return False
