from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional


def _global_pos_from_app() -> Any:
    try:
        from PySide6 import QtGui
        p = QtGui.QCursor.pos()
        return p if p is not None else None
    except Exception:
        return None


def _pos_from_global(widget: Any, global_pos: Any) -> Any:
    if widget is None or global_pos is None:
        return None
    m = getattr(widget, "mapFromGlobal", None)
    if not callable(m):
        return None
    try:
        return m(global_pos)
    except Exception:
        return None


@dataclass(slots=True)
class CommandContext:
    widget: Any = None
    scope: str = "*"
    source: str = ""
    event: Any = None
    key: Any = None
    pos: Any = None
    global_pos: Any = None
    start_pos: Any = None
    start_global_pos: Any = None
    extras: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def build(widget: Any = None, scope: Optional[str] = None, *, source: str = "", event: Any = None, key: Any = None, start_pos: Any = None, start_global_pos: Any = None, extras: Optional[Dict[str, Any]] = None) -> "CommandContext":
        sc = "*" if not scope else str(scope)
        ctx = CommandContext(widget=widget, scope=sc, source=str(source or ""), event=event, key=key)
        ctx.global_pos = _global_pos_from_app()
        ctx.pos = _pos_from_global(widget, ctx.global_pos)
        ctx.start_pos = start_pos
        ctx.start_global_pos = start_global_pos
        if isinstance(extras, dict) and extras:
            ctx.extras.update(extras)
        return ctx

    def get(self, key: str, default: Any = None) -> Any:
        k = str(key)
        try:
            if k in self.extras:
                return self.extras.get(k)
        except Exception:
            pass
        try:
            if hasattr(self, k):
                return getattr(self, k)
        except Exception:
            pass
        return default

    def get_many(self, keys, default: Any = None) -> list:
        try:
            return [self.get(k, default) for k in (keys or [])]
        except Exception:
            return []

    def put(self, key: str, value: Any) -> "CommandContext":
        self.extras[str(key)] = value
        return self

    def put_default(self, key: str, value: Any) -> "CommandContext":
        k = str(key)
        if k not in self.extras:
            self.extras[k] = value
        return self

    def merge(self, extras: Optional[Mapping[str, Any]]) -> "CommandContext":
        if not extras:
            return self
        try:
            for k, v in extras.items():
                self.extras[str(k)] = v
        except Exception:
            pass
        return self

    def snapshot_start(self) -> "CommandContext":
        if self.start_global_pos is None:
            self.start_global_pos = self.global_pos
        if self.start_pos is None:
            self.start_pos = self.pos
        return self

    def to_debug_dict(self) -> Dict[str, Any]:
        try:
            extras = dict(self.extras or {})
        except Exception:
            extras = {}
        return {
            "scope": self.scope,
            "source": self.source,
            "pos": self.pos,
            "global_pos": self.global_pos,
            "start_pos": self.start_pos,
            "start_global_pos": self.start_global_pos,
            "widget_type": getattr(getattr(self.widget, "__class__", None), "__name__", None),
            "event_type": getattr(getattr(self.event, "__class__", None), "__name__", None),
            "key": self.key,
            "extras": extras,
        }

    def to_debug_text(self) -> str:
        return str(self.to_debug_dict())

    def print_debug(self, printer=print) -> None:
        try:
            printer(self.to_debug_dict())
        except Exception:
            try:
                printer(self.to_debug_text())
            except Exception:
                pass
