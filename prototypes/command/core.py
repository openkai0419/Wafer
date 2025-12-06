from __future__ import annotations
from typing import Any, Callable, Dict, List, Optional
import json
from dataclasses import dataclass, field
from ..utils import CommandPayload


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
    action_group: str = ""
    func: Optional[Callable[..., Any]] = None


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
    return {p.name: kwargs.get(p.name, p.default) for p in meta.params}


def create_command_from_meta(meta: CommandMeta) -> type[CommandBase]:
    class _Cmd(CommandBase):
        pass
    _Cmd.meta = meta
    fn = getattr(meta, "func", None)
    if callable(fn):
        def _wrapped_execute(self, **kwargs):
            return fn(**kwargs)
        setattr(_Cmd, "execute", _wrapped_execute)
    return _Cmd


def register_command_defs(defs: List[Dict[str, Any]]):
    from .state import ActionGroupStateManager
    r = CommandRegistry()
    state_manager = ActionGroupStateManager()
    for d in defs:
        meta = d["meta"]
        r.register(create_command_from_meta(meta))
        if not (meta.action_group and meta.checkable):
            continue
        path = d.get("path", "")
        command_id = path.split("/")[-1] if "/" in path else path
        if command_id:
            state_manager.register_member(meta.action_group, command_id)

def create_cycle_command(group_name: str, display: str, hotkey: str = "") -> Dict[str, Any]:
    from .ui import CommandMenuBuilder
    def _cycle_func():
        builder = CommandMenuBuilder()
        result = builder.cycle_action_group(group_name)
        if result:
            print(f"Cycled to: {result}")
    return {
        "path": f"cycle_{group_name}",
        "meta": CommandMeta(
            display=display,
            hotkey=hotkey,
            func=_cycle_func
        )
    }
