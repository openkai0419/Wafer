from __future__ import annotations
import os
from typing import Any
from pathlib import Path
from ....utils.profiling import profiler
from ....utils.json_io import read_json_file, write_json_file
from ....utils.logs import AppLogger
from .payload import CommandPayload


class PersistentStore:
    def __init__(self, path: Path):
        self._map: dict[str, Any] = {}
        self._buffer: dict[str, Any] = {}
        self._loaded = False
        self._path = path
        self._flush_pending = False

    def _ensure_loaded(self):
        if self._loaded:
            return
        self._loaded = True
        data = read_json_file(self._path, {})
        if isinstance(data, dict):
            self._map = {str(k): v for k, v in data.items() if isinstance(v, dict)}
        else:
            self._map = {}

    def _flush(self) -> bool:
        if not self._buffer:
            return True
        self._map.update(self._buffer)
        self._buffer.clear()
        self._flush_pending = False
        return bool(write_json_file(self._path, self._map, indent=2, ensure_ascii=False))

    def _get_raw(self, key: str) -> dict[str, Any]:
        self._ensure_loaded()
        if key in self._buffer:
            return self._buffer[key]
        return self._map.get(key, {})

    def _set_raw(self, key: str, value: dict[str, Any]) -> bool:
        self._ensure_loaded()
        self._buffer[str(key)] = value
        self._flush_pending = True
        return True

    def commit(self) -> bool:
        if not self._flush_pending:
            return True
        return self._flush()

    def clear(self, key: str | None = None) -> bool:
        self._ensure_loaded()
        if key is None:
            self._map.clear()
            self._buffer.clear()
        else:
            k = str(key)
            self._map.pop(k, None)
            self._buffer.pop(k, None)
        return self._flush()


class CommandOptionStore(PersistentStore):
    _instance: CommandOptionStore | None = None
    _initialized = False
    _default_path: Path | None = None

    @classmethod
    def instance(cls) -> CommandOptionStore:
        if cls._instance is None:
            inst = object.__new__(cls)
            if cls._default_path is not None:
                PersistentStore.__init__(inst, cls._default_path)
            else:
                PersistentStore.__init__(inst, Path(os.devnull))
                inst._loaded = True
            cls._initialized = True
            cls._instance = inst
        return cls._instance

    @classmethod
    def configure(cls, path: str | Path) -> CommandOptionStore:
        cls._default_path = Path(path)
        inst = cls.instance()
        if inst._path != cls._default_path:
            inst._reconfigure(cls._default_path)
        return inst

    def _reconfigure(self, path: Path) -> None:
        self._path = Path(path)
        self._map = {}
        self._buffer = {}
        self._loaded = False
        self._flush_pending = False

    @profiler.profile
    def get(self, command_id: str) -> CommandPayload:
        v = self._get_raw(command_id)
        if isinstance(v, dict) and "id" in v:
            cid = v.get("id", command_id)
            args = v.get("args")
            if not isinstance(args, dict):
                args = {}
            return CommandPayload(str(cid), args)
        if not isinstance(v, dict):
            return CommandPayload(command_id, {})
        return CommandPayload(command_id, v)

    def set(self, command_id: str, options: dict[str, Any] | CommandPayload) -> bool:
        if isinstance(options, CommandPayload):
            return self._set_raw(str(command_id), {"id": options.id, "args": options.args})
        return self._set_raw(str(command_id), {"id": str(command_id), "args": options or {}})


class ActionGroupStateManager:
    _instance: ActionGroupStateManager | None = None

    @classmethod
    def instance(cls) -> ActionGroupStateManager:
        if cls._instance is None:
            inst = object.__new__(cls)
            inst._group_members = {}
            inst._command_to_group = {}
            cls._instance = inst
        return cls._instance

    def register_member(self, group_name: str, command_id: str):
        if group_name not in self._group_members:
            self._group_members[group_name] = []
        if command_id not in self._group_members[group_name]:
            self._group_members[group_name].append(command_id)
        self._command_to_group[command_id] = group_name

    def get_members(self, group_name: str) -> list[str]:
        return self._group_members.get(group_name, [])

    def get_group_for_command(self, command_id: str) -> str | None:
        return self._command_to_group.get(command_id)

    @profiler.profile
    def find_current(self, group_name: str, registry) -> str | None:
        members = self._group_members.get(group_name)
        if not members:
            return None
        for member in members:
            cmd = registry.get_command(member)
            if cmd is None:
                continue
            resolver = cmd.meta.checked
            if resolver is None:
                continue
            try:
                if bool(resolver()):
                    return member
            except Exception as e:
                AppLogger.warning(f"checked resolver failed for '{member}' in group '{group_name}': {e}")
        return None
