from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from collections.abc import Mapping

from ....utils.logs import AppLogger


def _zero_point() -> Any:
    try:
        from PySide6 import QtCore

        return QtCore.QPoint()
    except (ImportError, RuntimeError):
        return (0, 0)


def _global_pos_from_app() -> Any:
    try:
        from PySide6 import QtGui

        p = QtGui.QCursor.pos()
        return p if p is not None else None
    except (ImportError, ModuleNotFoundError):
        return None
    except Exception as e:
        AppLogger.warning("QCursor.pos() failed", exc=e)
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


def _wheel_steps_from_event(event: Any) -> int | None:
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
    pos: Any = None
    global_pos: Any = None
    wheel_steps: int = 1
    extras: dict[str, Any] = field(default_factory=dict)

    event: Any = None
    start_pos: Any = None
    start_global_pos: Any = None

    _widget: Any = field(default=None, repr=False)
    _scope: str = field(default="*", repr=False)
    _source: str = field(default="", repr=False)
    _widget_cache: dict[str, Any] = field(default_factory=dict, repr=False)

    @staticmethod
    def build(
        widget: Any = None, scope: str | None = None, *, source: str = "", event: Any = None, start_pos: Any = None, start_global_pos: Any = None, extras: dict[str, Any] | None = None
    ) -> CommandContext:
        ctx = CommandContext()
        ctx._widget = widget
        ctx._scope = "*" if not scope else str(scope)
        ctx._source = str(source or "")
        ctx.event = event
        ctx.global_pos = _global_pos_from_event(event) or _global_pos_from_app() or _zero_point()
        ctx.pos = _local_pos_from_event(event) or _pos_from_global(widget, ctx.global_pos) or _zero_point()
        ctx.start_pos = start_pos
        ctx.start_global_pos = start_global_pos
        ws = _wheel_steps_from_event(event)
        ctx.wheel_steps = int(ws) if ws is not None else 1
        if isinstance(extras, dict) and extras:
            ctx.extras.update(extras)
        return ctx

    def get_event(self, default: Any = None) -> Any:
        return self.event if self.event is not None else default

    @staticmethod
    def _merge_seed(ctx: CommandContext, seed: CommandContext | None, *, prefer_seed: bool) -> CommandContext:
        if seed is None:
            return ctx
        try:
            for attr in ("pos", "global_pos", "start_pos", "start_global_pos"):
                sv = getattr(seed, attr, None)
                if sv is not None and (prefer_seed or getattr(ctx, attr) is None):
                    setattr(ctx, attr, sv)
            sw = getattr(seed, "wheel_steps", None)
            if sw and (prefer_seed or not getattr(ctx, "wheel_steps", None)):
                ctx.wheel_steps = int(sw)
            seed_widget = getattr(seed, "_widget", None)
            if seed_widget is not None and (prefer_seed or ctx._widget is None):
                ctx._widget = seed_widget
            seed_scope = getattr(seed, "_scope", "*")
            if seed_scope and seed_scope != "*" and (prefer_seed or ctx._scope == "*"):
                ctx._scope = seed_scope
            for k, v in (getattr(seed, "extras", None) or {}).items():
                if prefer_seed:
                    ctx.extras[str(k)] = v
                else:
                    ctx.put_default(str(k), v)
        except Exception as e:
            AppLogger.warning("CommandContext._merge_seed failed", exc=e)
        return ctx

    @staticmethod
    def merge_seed_prefer_seed(ctx: CommandContext, seed: CommandContext | None) -> CommandContext:
        return CommandContext._merge_seed(ctx, seed, prefer_seed=True)

    @staticmethod
    def merge_seed_prefer_ctx(ctx: CommandContext, seed: CommandContext | None) -> CommandContext:
        return CommandContext._merge_seed(ctx, seed, prefer_seed=False)

    @staticmethod
    def merge_seed(ctx: CommandContext, seed: CommandContext | None) -> CommandContext:
        return CommandContext.merge_seed_prefer_seed(ctx, seed)

    @classmethod
    def create(
        cls,
        widget: Any = None,
        scope: str | None = None,
        *,
        source: str = "",
        event: Any = None,
        start_pos: Any = None,
        start_global_pos: Any = None,
        extras: dict[str, Any] | None = None,
        seed: CommandContext | None = None,
    ) -> CommandContext:
        sc = scope
        if not sc and widget is not None:
            try:
                if hasattr(widget, "binding_scope") and callable(widget.binding_scope):
                    sc = str(widget.binding_scope() or "*")
            except Exception as e:
                AppLogger.warning("binding_scope() failed", exc=e)
                sc = "*"
        ctx = cls.build(widget, sc, source=source, event=event, start_pos=start_pos, start_global_pos=start_global_pos, extras=dict(extras or {}) or None)
        return cls.merge_seed(ctx, seed)

    def get(self, key: str, default: Any = None) -> Any:
        k = str(key)
        if k in self.extras:
            return self.extras[k]
        if not k.startswith("_") and hasattr(self, k):
            return getattr(self, k)
        return default

    def get_many(self, keys, default: Any = None) -> list:
        if not keys:
            return []
        return [self.get(k, default) for k in keys]

    def get_instance(self, name: str, default: Any = None) -> Any:
        xs = self.get_instances(name)
        return xs[0] if xs else default

    def get_instances(self, name: str, default: list | None = None) -> list:
        if not name:
            return [] if default is None else list(default)
        k = str(name)
        cache = self._widget_cache
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
            except (ImportError, RuntimeError):
                return list(xs)
        try:
            from ..binding.instance_registry import InstanceRegistry

            reg = InstanceRegistry.instance()
            xs = reg.get_all(k)
            cache[k] = tuple(xs)
            return list(xs) if xs else ([] if default is None else list(default))
        except Exception as e:
            AppLogger.warning("CommandContext.get_widgets failed", exc=e)
            cache[k] = ()
            return [] if default is None else list(default)

    def put(self, key: str, value: Any) -> CommandContext:
        self.extras[str(key)] = value
        return self

    def put_default(self, key: str, value: Any) -> CommandContext:
        k = str(key)
        if k not in self.extras:
            self.extras[k] = value
        return self

    def merge(self, extras: Mapping[str, Any] | None) -> CommandContext:
        if not extras:
            return self
        for k, v in extras.items():
            self.extras[str(k)] = v
        return self

    def to_debug_dict(self) -> dict[str, Any]:
        return {
            "info": {
                "scope": self._scope,
                "source": self._source,
                "widget_type": getattr(getattr(self._widget, "__class__", None), "__name__", None),
            },
            "pos": self.pos,
            "global_pos": self.global_pos,
            "start_pos": self.start_pos,
            "start_global_pos": self.start_global_pos,
            "wheel_steps": self.wheel_steps,
            "event_type": getattr(getattr(self.get_event(), "__class__", None), "__name__", None),
            "extras": dict(self.extras),
        }

    def to_debug_text(self) -> str:
        return str(self.to_debug_dict())

    def print_debug(self, printer=None) -> None:
        if printer is None:
            printer = AppLogger.debug
        printer(self.to_debug_text())
