from __future__ import annotations
from typing import Any, Callable, Dict, List, Optional
from pathlib import Path
import json
from ..utils import read_json_file, write_json_file, CommandPayload


def log_warning(message: str):
    print(f"WARNING: {message}")


def log_error(message: str):
    print(f"ERROR: {message}")


class CommandOptionStore:
    _instance: Optional["CommandOptionStore"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._map = {}
            cls._instance._loaded = False
            cls._instance._path = Path(__file__).resolve().parent.parent / ".command_options.json"
        return cls._instance

    def _ensure_loaded(self):
        if self._loaded:
            return
        self._loaded = True
        data = read_json_file(self._path, {})
        if isinstance(data, dict):
            try:
                self._map = {str(k): v for k, v in data.items() if isinstance(v, dict)}
            except Exception:
                self._map = {}
        else:
            self._map = {}

    def _flush(self) -> bool:
        return bool(write_json_file(self._path, self._map, indent=2, ensure_ascii=False))

    def get(self, command_id: str) -> CommandPayload:
        self._ensure_loaded()
        v = self._map.get(command_id, {})
        try:
            if isinstance(v, dict) and "id" in v:
                return CommandPayload(str(v["id"]), v.get("args"))
            return CommandPayload(command_id, v if isinstance(v, dict) else {})
        except Exception:
            return CommandPayload(command_id, {})

    def set(self, command_id: str, options: Dict[str, Any] | CommandPayload) -> bool:
        self._ensure_loaded()
        if isinstance(options, CommandPayload):
            self._map[str(command_id)] = {"id": options.id, "args": options.args}
        else:
            self._map[str(command_id)] = {"id": str(command_id), "args": options or {}}
        return self._flush()

    def clear(self, command_id: Optional[str] = None) -> bool:
        self._ensure_loaded()
        if command_id is None:
            self._map.clear()
        else:
            self._map.pop(str(command_id), None)
        return self._flush()


class ActionGroupStateManager:
    _instance: Optional["ActionGroupStateManager"] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._group_states = {}
            cls._instance._group_members = {}
            cls._instance._command_to_group = {}
            cls._instance._check_states = {}
            cls._instance._observers = []
        return cls._instance
    
    def add_observer(self, observer: Callable[[str, str], None]):
        if observer not in self._observers:
            self._observers.append(observer)
    
    def remove_observer(self, observer: Callable[[str, str], None]):
        if observer in self._observers:
            self._observers.remove(observer)
    
    def _notify_observers(self, group_name: str, command_id: str):
        for observer in self._observers:
            try:
                observer(group_name, command_id)
            except Exception as e:
                log_error(f"Observer notification failed: {e}")
    
    def register_member(self, group_name: str, command_id: str):
        if group_name not in self._group_members:
            self._group_members[group_name] = []
        if command_id not in self._group_members[group_name]:
            self._group_members[group_name].append(command_id)
        self._command_to_group[command_id] = group_name
    
    def get_members(self, group_name: str) -> List[str]:
        return self._group_members.get(group_name, [])
    
    def get_group_for_command(self, command_id: str) -> Optional[str]:
        return self._command_to_group.get(command_id)
    
    def get_current(self, group_name: str) -> Optional[str]:
        if group_name in self._group_states:
            return self._group_states[group_name]
        result = self._load_state(group_name)
        if result:
            self._group_states[group_name] = result
        return result
    
    def set_current(self, group_name: str, command_id: str, save: bool = True):
        self._group_states[group_name] = command_id
        members = self._group_members.get(group_name, [])
        for member in members:
            self._check_states[member] = (member == command_id)
        if save:
            self._save_state(group_name, command_id)
        self._notify_observers(group_name, command_id)
    
    def cycle(self, group_name: str) -> Optional[str]:
        members = self._group_members.get(group_name)
        if not members:
            return None
        current = self.get_current(group_name)
        current_idx = members.index(current) if current in members else -1
        result = members[(current_idx + 1) % len(members)]
        self.set_current(group_name, result, save=True)
        return result
    
    def get_check_state(self, command_id: str) -> bool:
        return self._check_states.get(command_id, False)
    
    def set_check_state(self, command_id: str, checked: bool):
        self._check_states[command_id] = checked
    
    def _save_state(self, group_name: str, command_id: str):
        try:
            store = CommandOptionStore()
            store.set(f"__group__{group_name}", {"selected": command_id})
            members = self._group_members.get(group_name, [])
            for member in members:
                cur = store.get(member)
                opts = getattr(cur, "args", None)
                if not isinstance(opts, dict):
                    opts = opts.copy() if opts else {}
                opts["checked"] = (member == command_id)
                store.set(member, opts)
        except Exception as e:
            log_error(f"Failed to save action group state: {e}")
    
    def _load_state(self, group_name: str) -> Optional[str]:
        try:
            stored = CommandOptionStore().get(f"__group__{group_name}")
            args = getattr(stored, "args", None)
            if args and "selected" in args:
                return str(args["selected"])
        except Exception as e:
            log_warning(f"Failed to load action group state: {e}")
        
        members = self._group_members.get(group_name)
        if not members:
            return None
        
        store = CommandOptionStore()
        for member in members:
            try:
                stored = store.get(member)
                args = getattr(stored, "args", None)
                if args and args.get("checked"):
                    return member
            except Exception as e:
                log_warning(f"Failed to check member state: {e}")
        
        return None
    
    def find_default(self, group_name: str, registry) -> Optional[str]:
        members = self._group_members.get(group_name)
        if not members:
            return None
        for member in members:
            command_class = registry.get_command(member)
            if command_class and command_class.meta.default_checked:
                return member
        return None
