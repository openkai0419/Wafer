from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional

from source.common.errors import show_warning


def _zero_point() -> Any:
    try:
        from PySide6 import QtCore

        return QtCore.QPoint()
    except Exception:
        return (0, 0)


def _global_pos_from_app() -> Any:
    try:
        from PySide6 import QtGui
        p = QtGui.QCursor.pos()
        return p if p is not None else None
    except (ImportError, ModuleNotFoundError):
        return None
    except Exception as e:
        show_warning(None, "QCursor.pos() failed", exc=e)
        return None


def _global_pos_from_event(event: Any) -> Any:
    if event is None:
        return None
    gp = getattr(event, "globalPosition", None)
    if callable(gp):
        try:
            p = gp()
            return p.toPoint() if hasattr(p, "toPoint") else p
        except (RuntimeError, TypeError, AttributeError):
            return None
    gp = getattr(event, "globalPos", None)
    if callable(gp):
        try:
            return gp()
        except (RuntimeError, TypeError, AttributeError):
            return None
    return None


def _local_pos_from_event(event: Any) -> Any:
    if event is None:
        return None
    p = getattr(event, "position", None)
    if callable(p):
        try:
            v = p()
            return v.toPoint() if hasattr(v, "toPoint") else v
        except (RuntimeError, TypeError, AttributeError):
            return None
    p = getattr(event, "pos", None)
    if callable(p):
        try:
            return p()
        except (RuntimeError, TypeError, AttributeError):
            return None
    return None


def _pos_from_global(widget: Any, global_pos: Any) -> Any:
    if widget is None or global_pos is None:
        return None
    m = getattr(widget, "mapFromGlobal", None)
    if not callable(m):
        return None
    try:
        return m(global_pos)
    except (RuntimeError, TypeError, AttributeError):
        return None


def _wheel_steps_from_event(event: Any) -> Optional[int]:
    if event is None:
        return None
    ad = getattr(event, "angleDelta", None)
    if callable(ad):
        try:
            ay = int(ad().y())
            if ay:
                a = abs(ay)
                return max(1, int((a + 60) // 120))
        except (RuntimeError, TypeError, AttributeError, ValueError):
            pass
    pd = getattr(event, "pixelDelta", None)
    if callable(pd):
        try:
            py = int(pd().y())
            if py:
                p = abs(py)
                return max(1, int((p + 50) // 100))
        except (RuntimeError, TypeError, AttributeError, ValueError):
            pass
    return None


@dataclass(slots=True)
class CommandContext:
    widget: Any = None
    start_pos: Any = None
    start_global_pos: Any = None

    event: Any = None

    scope: str = "*"
    source: str = ""
    pos: Any = None
    global_pos: Any = None
    wheel_steps: int = 1
    extras: Dict[str, Any] = field(default_factory=dict)
    widget_cache: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def build(widget: Any = None, scope: Optional[str] = None, *, source: str = "", event: Any = None, start_pos: Any = None, start_global_pos: Any = None, extras: Optional[Dict[str, Any]] = None) -> "CommandContext":
        sc = "*" if not scope else str(scope)
        ctx = CommandContext(widget=widget, scope=sc, source=str(source or ""))
        ctx.event = event if str(source or "").startswith("drop") else None
        ctx.global_pos = _global_pos_from_event(event) or _global_pos_from_app() or _zero_point()
        ctx.pos = _local_pos_from_event(event) or _pos_from_global(widget, ctx.global_pos) or _zero_point()
        ctx.start_pos = start_pos if start_pos is not None else None
        ctx.start_global_pos = start_global_pos if start_global_pos is not None else None
        ws = _wheel_steps_from_event(event)
        ctx.wheel_steps = int(ws) if ws is not None else 1
        if isinstance(extras, dict) and extras:
            ctx.extras.update(extras)
        return ctx

    def get_event(self, default: Any = None) -> Any:
        ev = getattr(self, "event", None)
        return ev if ev is not None else default

    @staticmethod
    def _merge_seed(ctx: "CommandContext", seed: Optional["CommandContext"], *, prefer_seed: bool) -> "CommandContext":
        if seed is None:
            return ctx
        try:
            if prefer_seed:
                if seed.pos is not None:
                    ctx.pos = seed.pos
                if seed.global_pos is not None:
                    ctx.global_pos = seed.global_pos
                if seed.start_pos is not None:
                    ctx.start_pos = seed.start_pos
                if seed.start_global_pos is not None:
                    ctx.start_global_pos = seed.start_global_pos
                if getattr(seed, "wheel_steps", None):
                    ctx.wheel_steps = int(seed.wheel_steps)
                if seed.widget is not None:
                    ctx.widget = seed.widget
                if getattr(seed, "scope", None) and seed.scope != "*":
                    ctx.scope = seed.scope
                for k, v in (getattr(seed, "extras", None) or {}).items():
                    ctx.extras[str(k)] = v
            else:
                if ctx.pos is None and seed.pos is not None:
                    ctx.pos = seed.pos
                if ctx.global_pos is None and seed.global_pos is not None:
                    ctx.global_pos = seed.global_pos
                if ctx.start_pos is None and seed.start_pos is not None:
                    ctx.start_pos = seed.start_pos
                if ctx.start_global_pos is None and seed.start_global_pos is not None:
                    ctx.start_global_pos = seed.start_global_pos
                if not getattr(ctx, "wheel_steps", None) and getattr(seed, "wheel_steps", None):
                    ctx.wheel_steps = int(seed.wheel_steps)
                if ctx.widget is None and seed.widget is not None:
                    ctx.widget = seed.widget
                if ctx.scope == "*" and getattr(seed, "scope", "*") and seed.scope != "*":
                    ctx.scope = seed.scope
                for k, v in (getattr(seed, "extras", None) or {}).items():
                    ctx.put_default(str(k), v)
        except Exception as e:
            show_warning(None, "CommandContext._merge_seed failed", exc=e)
        return ctx

    @staticmethod
    def merge_seed_prefer_seed(ctx: "CommandContext", seed: Optional["CommandContext"]) -> "CommandContext":
        return CommandContext._merge_seed(ctx, seed, prefer_seed=True)

    @staticmethod
    def merge_seed_prefer_ctx(ctx: "CommandContext", seed: Optional["CommandContext"]) -> "CommandContext":
        return CommandContext._merge_seed(ctx, seed, prefer_seed=False)

    @staticmethod
    def merge_seed(ctx: "CommandContext", seed: Optional["CommandContext"]) -> "CommandContext":
        return CommandContext.merge_seed_prefer_seed(ctx, seed)

    @classmethod
    def create(cls, widget: Any = None, scope: Optional[str] = None, *, source: str = "", event: Any = None, start_pos: Any = None, start_global_pos: Any = None, extras: Optional[Dict[str, Any]] = None, seed: Optional["CommandContext"] = None) -> "CommandContext":
        sc = scope
        if not sc and widget is not None:
            try:
                if hasattr(widget, "binding_scope") and callable(widget.binding_scope):
                    sc = str(widget.binding_scope() or "*")
            except Exception as e:
                show_warning(None, "binding_scope() failed", exc=e)
                sc = "*"
        ctx = cls.build(widget, sc, source=source, event=event, start_pos=start_pos, start_global_pos=start_global_pos, extras=dict(extras or {}) or None)
        return cls.merge_seed(ctx, seed)

    def get(self, key: str, default: Any = None) -> Any:
        k = str(key)
        try:
            if k in self.extras:
                return self.extras.get(k)
        except Exception as e:
            show_warning(None, f"CommandContext.get extras access failed: {k}", exc=e)
        try:
            if hasattr(self, k):
                return getattr(self, k)
        except Exception as e:
            show_warning(None, f"CommandContext.get attr access failed: {k}", exc=e)
        return default

    def get_many(self, keys, default: Any = None) -> list:
        if not keys:
            return []
        try:
            return [self.get(k, default) for k in keys]
        except TypeError:
            return []

    def get_instance(self, name: str, default: Any = None) -> Any:
        xs = self.get_instances(name)
        return xs[0] if xs else default

    def get_instances(self, name: str, default: Optional[list] = None) -> list:
        if not name:
            return [] if default is None else list(default)
        k = str(name)
        cache = self.widget_cache
        if k in cache:
            xs = cache.get(k)
            if not xs:
                return [] if default is None else list(default)
            try:
                from ..binding.instance_registry import InstanceRegistry

                reg = InstanceRegistry.instance()
                if any(not reg.is_valid(w) for w in xs):
                    cache.pop(k, None)
                else:
                    return list(xs)
            except Exception:
                return list(xs)
        try:
            from ..binding.instance_registry import InstanceRegistry

            reg = InstanceRegistry.instance()
            xs = reg.get_all(k)
            cache[k] = tuple(xs)
            return list(xs) if xs else ([] if default is None else list(default))
        except Exception as e:
            show_warning(None, "CommandContext.get_widgets failed", exc=e)
            cache[k] = ()
            return [] if default is None else list(default)

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
        except Exception as e:
            show_warning(None, "CommandContext.merge failed", exc=e)
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
        except (TypeError, ValueError):
            extras = {}
        return {
            "scope": self.scope,
            "source": self.source,
            "pos": self.pos,
            "global_pos": self.global_pos,
            "start_pos": self.start_pos,
            "start_global_pos": self.start_global_pos,
            "wheel_steps": self.wheel_steps,
            "event_type": getattr(getattr(self.get_event(), "__class__", None), "__name__", None),
            "widget_type": getattr(getattr(self.widget, "__class__", None), "__name__", None),
            "extras": extras,
        }

    def to_debug_text(self) -> str:
        return str(self.to_debug_dict())

    def print_debug(self, printer=print) -> None:
        try:
            printer(self.to_debug_dict())
        except Exception as e:
            show_warning(None, "CommandContext.print_debug failed", exc=e)
            try:
                printer(self.to_debug_text())
            except Exception as e2:
                show_warning(None, "CommandContext.print_debug fallback failed", exc=e2)
                return
