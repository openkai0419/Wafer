from __future__ import annotations
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING
from dataclasses import dataclass, field
from PySide6 import QtCore, QtGui
from ..lang.manager import TranslatorMixin

@dataclass
class CommandParameter:
    name: str
    type: type
    default: Any = None
    description: str = ""
    choices: Optional[List[Any]] = None
    min_value: Optional[Any] = None
    max_value: Optional[Any] = None

@dataclass
class CommandMetadata:
    name: str
    category: str
    description: str
    parameters: List[CommandParameter] = field(default_factory=list)
    hotkey: str = ""
    icon: str = ""
    undoable: bool = True

class Command:
    def __init__(self, metadata: CommandMetadata):
        self.metadata = metadata
        self._undo_data: Optional[Dict[str, Any]] = None
    
    def execute(self, **kwargs) -> Any:
        raise NotImplementedError
    
    def undo(self) -> None:
        if not self.metadata.undoable:
            raise RuntimeError(f"Command {self.metadata.name} is not undoable")
    
    def validate_params(self, **kwargs) -> bool:
        for param in self.metadata.parameters:
            value = kwargs.get(param.name, param.default)
            if value is None and param.default is None:
                return False
            if param.choices and value not in param.choices:
                return False
            if param.min_value is not None and value < param.min_value:
                return False
            if param.max_value is not None and value > param.max_value:
                return False
        return True

class CommandRegistry:
    _instance: Optional[CommandRegistry] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._commands: Dict[str, type[Command]] = {}
            cls._instance._history: List[Command] = []
            cls._instance._history_index: int = -1
        return cls._instance
    
    def register(self, command_class: type[Command]) -> None:
        self._commands[command_class.metadata.name] = command_class
    
    def execute(self, command_name: str, **kwargs) -> Any:
        if command_name not in self._commands:
            raise ValueError(f"Command {command_name} not found")
        
        command_class = self._commands[command_name]
        command = command_class(command_class.metadata)
        
        if not command.validate_params(**kwargs):
            raise ValueError(f"Invalid parameters for command {command_name}")
        
        result = command.execute(**kwargs)
        
        if command.metadata.undoable:
            if self._history_index < len(self._history) - 1:
                self._history = self._history[:self._history_index + 1]
            self._history.append(command)
            self._history_index = len(self._history) - 1
        
        return result
    
    def undo(self) -> None:
        if self._history_index < 0:
            return
        command = self._history[self._history_index]
        command.undo()
        self._history_index -= 1
    
    def redo(self) -> None:
        if self._history_index >= len(self._history) - 1:
            return
        self._history_index += 1
        command = self._history[self._history_index]
        command.execute()
    
    def get_command(self, name: str) -> Optional[type[Command]]:
        return self._commands.get(name)
    
    def get_all_commands(self) -> Dict[str, type[Command]]:
        return self._commands.copy()
    
    def get_commands_by_category(self, category: str) -> Dict[str, type[Command]]:
        return {name: cmd for name, cmd in self._commands.items() 
                if cmd.metadata.category == category}