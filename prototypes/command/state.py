from __future__ import annotations
from typing import Any, Dict, Optional
from pathlib import Path
import json
from ..utils import to_payload_json, read_json_file, write_json_file


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

    def _flush(self):
        write_json_file(self._path, self._map, indent=2, ensure_ascii=False)

    def get(self, command_id: str) -> str:
        self._ensure_loaded()
        v = self._map.get(command_id, {})
        if isinstance(v, dict) and "id" in v and "args" in v:
            try:
                return to_payload_json({"id": str(v.get("id")), "args": dict(v.get("args") or {})})
            except Exception:
                return to_payload_json({"id": str(command_id), "args": {}})
        try:
            return to_payload_json({"id": str(command_id), "args": dict(v if isinstance(v, dict) else {})})
        except Exception:
            return to_payload_json({"id": str(command_id), "args": {}})

    def get_payload(self, command_id: str) -> Dict[str, Any]:
        self._ensure_loaded()
        v = self._map.get(command_id, {})
        if isinstance(v, dict) and "id" in v and "args" in v:
            return {"id": str(v.get("id")), "args": dict(v.get("args") or {})}
        return {"id": command_id, "args": dict(v if isinstance(v, dict) else {})}

    def set(self, command_id: str, options: Dict[str, Any]):
        self._ensure_loaded()
        self._map[str(command_id)] = {"id": str(command_id), "args": dict(options or {})}
        self._flush()

    def set_payload(self, command_id: str, payload: Dict[str, Any]):
        self._ensure_loaded()
        if isinstance(payload, dict) and "id" in payload and "args" in payload:
            self._map[str(command_id)] = {"id": str(payload.get("id")), "args": dict(payload.get("args") or {})}
        else:
            self._map[str(command_id)] = {"id": str(command_id), "args": dict(payload if isinstance(payload, dict) else {})}
        self._flush()

    def clear(self, command_id: Optional[str] = None):
        self._ensure_loaded()
        if command_id is None:
            self._map.clear()
        else:
            self._map.pop(str(command_id), None)
        self._flush()
