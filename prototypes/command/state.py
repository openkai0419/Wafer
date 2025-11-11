from __future__ import annotations
from typing import Any, Dict, Optional
from pathlib import Path
import json
from ..utils import read_json_file, write_json_file, CommandPayload


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
            if isinstance(v, dict) and "id" in v and "args" in v:
                return CommandPayload(str(v.get("id")), dict(v.get("args") or {}))
            return CommandPayload(command_id, dict(v if isinstance(v, dict) else {}))
        except Exception:
            return CommandPayload(command_id, {})

    def set(self, command_id: str, options: Dict[str, Any] | CommandPayload) -> bool:
        self._ensure_loaded()
        if isinstance(options, CommandPayload):
            self._map[str(command_id)] = {"id": options.id, "args": dict(options.args or {})}
        else:
            self._map[str(command_id)] = {"id": str(command_id), "args": dict(options or {})}
        return self._flush()

    def clear(self, command_id: Optional[str] = None) -> bool:
        self._ensure_loaded()
        if command_id is None:
            self._map.clear()
        else:
            self._map.pop(str(command_id), None)
        return self._flush()
