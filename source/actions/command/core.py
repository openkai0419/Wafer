from __future__ import annotations
from typing import Any, Callable, Dict, List, Optional, Sequence, Mapping
import json
import inspect
from dataclasses import dataclass, field
from source.common.profiling import profiler
from source.common.logs import AppLogger
from .payload import CommandPayload
from .context import CommandContext

COMMAND_MENU_MARKER = "__CommandMenuBuilder_Menu__"


class CommandParam:
    __slots__ = ("name", "type", "default", "description", "choices", "min_value", "max_value", "widget_type")

    def __init__(
        self,
        *,
        name: str,
        value: Any,
        description: str = "",
        default: Any = inspect._empty,
        min_value: Optional[Any] = None,
        max_value: Optional[Any] = None,
        widget_type: str = "auto",
    ):
        if not name:
            raise ValueError("name is required")
        if isinstance(value, (list, tuple)):
            xs = list(value)
            if not xs:
                raise ValueError("value choices must not be empty")
            self.choices = xs
            self.default = xs[0] if default is inspect._empty else default
            self.type = type(self.default) if self.default is not None else type(xs[0])
        else:
            self.choices = None
            self.default = value if default is inspect._empty else default
            self.type = type(self.default) if self.default is not None else (type(value) if value is not None else str)
        self.name = name
        self.description = description
        self.min_value = min_value
        self.max_value = max_value
        self.widget_type = widget_type


@dataclass
class CommandMeta:
    path: str = ""
    id: str = ""
    display: str = ""
    hidden: bool = False
    params: List[CommandParam] = field(default_factory=list)
    hotkey: str = ""
    icon: str = ""
    has_options: bool = False
    checkable: bool = False
    default_checked: bool = False
    action_group: str = ""
    category: str = ""
    target_widgets: List[str] = field(default_factory=list)
    func: Optional[Callable[..., Any]] = None
    drag_callbacks: Optional[Dict[str, Callable[..., Any]]] = None
    drop_callbacks: Optional[Dict[str, Callable[..., Any]]] = None
    drop_acceptor: Optional[Callable[..., bool]] = None

    def __post_init__(self):
        if self.hotkey:
            raise ValueError("hotkey must not be set on CommandMeta; it is resolved from bindings")
        self.has_options = bool(self.has_options or self.params)


class CommandBase:
    meta: CommandMeta = None

    def __init__(self):
        self._last_kwargs: Optional[Dict[str, Any]] = None

    def execute(self, **kwargs) -> Any:
        raise NotImplementedError

    def undo(self) -> None:
        pass

    def call_execute(self, **kwargs) -> Any:
        if self.meta:
            args = _build_args(self.meta, kwargs)
        else:
            args = dict(kwargs)
        self._last_kwargs = dict(args)
        return self.execute(**args)


class CommandRegistry:
    _instance: Optional[CommandRegistry] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._commands = {}
        return cls._instance

    def register(self, command_class: type[CommandBase]) -> None:
        cid = getattr(command_class.meta, "id", None)
        if not cid:
            raise ValueError("Command id is required")
        if cid in self._commands:
            raise ValueError(f"Duplicate command id: {cid}")
        self._commands[cid] = command_class

    @profiler.profile
    def execute(self, command_name: str, ctx=None, **kwargs) -> Any:
        if command_name not in self._commands:
            raise ValueError(f"Command {command_name} not found")
        if ctx is None:
            ctx = kwargs.pop("ctx", None)
        if ctx is None:
            raise ValueError("ctx is required")
        kwargs["ctx"] = ctx
        command_class = self._commands[command_name]
        meta = getattr(command_class, "meta", None)
        if meta and getattr(meta, "category", "") in ("drag", "drop"):
            if getattr(ctx, "event", None) is None:
                raise ValueError(f"Command '{command_name}' (category={meta.category}) requires event")
        command = command_class()
        AppLogger.debug(f'cmd: {command_name}')
        return command.call_execute(**kwargs) if hasattr(command, "call_execute") else command.execute(**kwargs)

    def has_command(self, name: str) -> bool:
        return name in self._commands

    def get_command(self, name: str) -> Optional[type[CommandBase]]:
        return self._commands.get(name)

    def get_all_commands(self) -> Dict[str, type[CommandBase]]:
        return self._commands.copy()

    def get_commands_by_category(self, category: str, widget_scope: Optional[str] = None) -> Dict[str, type[CommandBase]]:
        result = {}
        for cid, cmd_class in self._commands.items():
            meta = getattr(cmd_class, "meta", None)
            if meta and getattr(meta, "category", "") == category:
                target_widgets = getattr(meta, "target_widgets", [])
                if not target_widgets:
                    result[cid] = cmd_class
                elif widget_scope and widget_scope in target_widgets:
                    result[cid] = cmd_class
        return result

    def get_all_categories(self) -> List[str]:
        categories = set()
        for cmd_class in self._commands.values():
            meta = getattr(cmd_class, "meta", None)
            if meta and getattr(meta, "category", ""):
                categories.add(meta.category)
        return sorted(categories)


class DropAcceptRegistry:
    _instance: Optional[DropAcceptRegistry] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._acceptors = {}
        return cls._instance

    def register(self, widget_scope: str, acceptor: Callable[..., bool]) -> None:
        if not widget_scope:
            raise ValueError("widget_scope is required")
        if not callable(acceptor):
            raise ValueError("acceptor must be callable")
        items = self._acceptors.get(widget_scope)
        if items is None:
            self._acceptors[widget_scope] = [acceptor]
            return
        if any(a is acceptor for a in items):
            return
        items.append(acceptor)

    def resolve(self, widget_scope: Optional[str]) -> Sequence[Callable[..., bool]]:
        if not widget_scope:
            widget_scope = "*"
        if widget_scope == "*":
            return tuple(self._acceptors.get("*") or ())

        out: List[Callable[..., bool]] = []
        for a in self._acceptors.get(widget_scope) or ():
            if callable(a) and not any(x is a for x in out):
                out.append(a)
        for a in self._acceptors.get("*") or ():
            if callable(a) and not any(x is a for x in out):
                out.append(a)
        return tuple(out)


def register_drop_accept(widget_scope: str, acceptor: Callable[..., bool]) -> None:
    DropAcceptRegistry().register(widget_scope, acceptor)


def resolve_drop_accept(widget_scope: Optional[str]) -> Sequence[Callable[..., bool]]:
    return DropAcceptRegistry().resolve(widget_scope)


def validate_command_args(meta: CommandMeta, args: Dict[str, Any], *, require_all: bool = False) -> None:
    param_map = {p.name: p for p in (meta.params or [])}
    extra = set(args.keys()) - set(param_map.keys())
    if extra:
        raise ValueError(f"Unknown args for '{meta.id}': {sorted(extra)}")
    if require_all:
        missing = set(param_map.keys()) - set(args.keys())
        if missing:
            raise ValueError(f"Missing args for '{meta.id}': {sorted(missing)}")
    for name, value in args.items():
        p = param_map[name]
        if value is None:
            continue
        expected = p.type
        if expected is not None and not isinstance(value, expected):
            if expected is float and isinstance(value, int):
                continue
            raise TypeError(f"Arg '{name}' for '{meta.id}': expected {expected.__name__}, got {type(value).__name__}")
        if p.choices is not None and value not in p.choices:
            raise ValueError(f"Arg '{name}' for '{meta.id}': {value!r} not in {p.choices}")
        if p.min_value is not None and value < p.min_value:
            raise ValueError(f"Arg '{name}' for '{meta.id}': {value} < min {p.min_value}")
        if p.max_value is not None and value > p.max_value:
            raise ValueError(f"Arg '{name}' for '{meta.id}': {value} > max {p.max_value}")


def _build_args(meta: CommandMeta, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    if "ctx" not in kwargs:
        raise ValueError("ctx is required")
    params = {p.name: kwargs.get(p.name, p.default) for p in meta.params}
    params["ctx"] = kwargs["ctx"]
    return params


def _invoke_compatible(fn: Callable[..., Any], values: Dict[str, Any]) -> Any:
    sig = inspect.signature(fn)
    params = list(sig.parameters.values())

    used: set[str] = set()
    args: list[Any] = []
    kwargs: dict[str, Any] = {}
    has_varkw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params)

    for p in params:
        if p.kind == inspect.Parameter.POSITIONAL_ONLY:
            if p.name in values:
                args.append(values[p.name])
                used.add(p.name)
                continue
            if p.default is not inspect._empty:
                args.append(p.default)
                continue
            raise TypeError(f"Missing required positional-only argument: {p.name}")

    for p in params:
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        if p.name in values:
            kwargs[p.name] = values[p.name]
            used.add(p.name)

    if has_varkw:
        for k, v in values.items():
            if k not in used:
                kwargs[k] = v

    return fn(*args, **kwargs)


def invoke_compatible(fn: Callable[..., Any], values: Mapping[str, Any] | None = None) -> Any:
    if values is None:
        values = {}
    return _invoke_compatible(fn, dict(values))


def create_command_from_meta(meta: CommandMeta) -> type[CommandBase]:
    class _Cmd(CommandBase):
        pass
    _Cmd.meta = meta
    fn = getattr(meta, "func", None)
    if callable(fn):
        sig = inspect.signature(fn)
        accepts_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
        param_names = set(sig.parameters.keys())
        
        def _wrapped_execute(self, **kwargs):
            filtered_kwargs = dict(kwargs) if accepts_kwargs else {k: v for k, v in kwargs.items() if k in param_names}
            return invoke_compatible(fn, filtered_kwargs)
        setattr(_Cmd, "execute", _wrapped_execute)
    elif meta.drag_callbacks or meta.drop_callbacks:
        callbacks = dict(getattr(meta, "drag_callbacks", None) or {}) or dict(getattr(meta, "drop_callbacks", None) or {})

        def _dispatch_execute(self, **kwargs):
            ctx = kwargs.get("ctx")
            phase = None
            if ctx is not None:
                phase = ctx.get("phase")
            if not phase:
                return None
            cb = callbacks.get(str(phase))
            if not callable(cb):
                return None
            return invoke_compatible(cb, kwargs)

        setattr(_Cmd, "execute", _dispatch_execute)
    return _Cmd


def register_command_defs(defs: List[CommandMeta]):
    from .state import ActionGroupStateManager
    r = CommandRegistry()
    state_manager = ActionGroupStateManager()
    for meta in defs:

        acceptor = getattr(meta, "drop_acceptor", None)
        if callable(acceptor):
            scopes = getattr(meta, "target_widgets", None) or ["*"]
            for scope in scopes:
                DropAcceptRegistry().register(scope, acceptor)
        
        if meta.category == "drag" and not meta.drag_callbacks:
            raise ValueError(f"Command '{meta.id}' has category='drag' but missing drag_callbacks. Use drag_callbacks instead of func.")
        if meta.category == "drop" and not meta.drop_callbacks:
            raise ValueError(f"Command '{meta.id}' has category='drop' but missing drop_callbacks. Use drop_callbacks instead of func.")
        if meta.category == "drag" and meta.func:
            raise ValueError(f"Command '{meta.id}' has category='drag' but uses func. Use drag_callbacks instead.")
        if meta.category == "drop" and meta.func:
            raise ValueError(f"Command '{meta.id}' has category='drop' but uses func. Use drop_callbacks instead.")
        
        r.register(create_command_from_meta(meta))
        
        if not (meta.action_group and meta.checkable):
            continue
        if meta.id:
            state_manager.register_member(meta.action_group, meta.id)

def create_cycle_command(group_name: str, display: str) -> CommandMeta:
    from .ui import CommandMenuBuilder
    def _cycle_func():
        builder = CommandMenuBuilder()
        result = builder.cycle_action_group(group_name)
        if result:
            AppLogger.debug(f"Cycled to: {result}")
    return CommandMeta(
        path=f"cycle_{group_name}",
        display=display,
        func=_cycle_func,
    )
