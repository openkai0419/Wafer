from __future__ import annotations
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, field


@dataclass
class CommandParam:
    name: str
    type: type
    default: Any = None
    description: str = ""
    choices: Optional[List[Any]] = None
    min_value: Optional[Any] = None
    max_value: Optional[Any] = None
    widget_type: str = "auto"


@dataclass
class CommandMeta:
    id: str = ""
    display: str = ""
    params: List[CommandParam] = field(default_factory=list)
    hotkey: str = ""
    icon: str = ""
    has_options: bool = False
    checkable: bool = False
    default_checked: bool = False


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

    def execute(self, command_name: str, **kwargs) -> Any:
        if command_name not in self._commands:
            raise ValueError(f"Command {command_name} not found")
        command_class = self._commands[command_name]
        command = command_class()
        if hasattr(command, "call_execute"):
            return command.call_execute(**kwargs)
        return command.execute(**kwargs)

    def get_command(self, name: str) -> Optional[type[CommandBase]]:
        return self._commands.get(name)

    def get_all_commands(self) -> Dict[str, type[CommandBase]]:
        return self._commands.copy()


def _build_args(meta: CommandMeta, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    r = {}
    for p in meta.params:
        v = kwargs[p.name] if p.name in kwargs else p.default
        r[p.name] = v
    return r


def create_command_from_callable(meta: CommandMeta, func: Callable[..., Any]) -> type[CommandBase]:
    class _Cmd(CommandBase):
        pass

    _Cmd.meta = meta

    def _wrapped_execute(self, **kwargs):
        return func(**kwargs)

    setattr(_Cmd, "execute", _wrapped_execute)
    return _Cmd


def register_command_defs(defs: List[Dict[str, Any]]):
    r = CommandRegistry()
    for d in defs:
        meta = d["meta"]
        fn = d["func"]
        r.register(create_command_from_callable(meta, fn))
