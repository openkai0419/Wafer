from __future__ import annotations
from typing import Any
from collections.abc import Callable
from pathlib import Path
from ....core.profiling import profiler
from ....core.common.json_io import read_json_file, write_json_file
from ....core.platform.process_lock import file_lock
from ....core.logs import AppLogger
from .payload import CommandPayload


class PersistentStore:
    def __init__(self, path: Path | None):
        self._map: dict[str, Any] = {}
        self._buffer: dict[str, Any] = {}
        self._loaded = False
        self._path = path
        self._flush_pending = False

    def _read_file(self) -> dict[str, Any]:
        data = read_json_file(self._path, {}) if self._path is not None else {}
        if not isinstance(data, dict):
            return {}
        return {str(k): v for k, v in data.items() if isinstance(v, dict)}

    def _ensure_loaded(self):
        if self._loaded:
            return
        self._loaded = True
        self._map = self._read_file()

    def _update_file(self, apply: Callable[[dict[str, Any]], None]) -> bool:
        if self._path is None:
            apply(self._map)
            return True
        try:
            with file_lock(f"{self._path}.lock"):
                latest = self._read_file()
                apply(latest)
                self._map = latest
                return bool(write_json_file(self._path, latest, indent=2, ensure_ascii=False))
        except TimeoutError as e:
            AppLogger.warning(f"Command options were not saved, the file stayed locked: {self._path}", exc=e)
            apply(self._map)
            return False

    def _flush(self) -> bool:
        if not self._buffer:
            return True
        changed = dict(self._buffer)
        self._buffer.clear()
        self._flush_pending = False
        return self._update_file(lambda m: m.update(changed))

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
            self._buffer.clear()
            self._flush_pending = False
            return self._update_file(lambda m: m.clear())
        k = str(key)
        self._buffer.pop(k, None)
        self._flush_pending = bool(self._buffer)
        return self._update_file(lambda m: m.pop(k, None))


class CommandOptionStore(PersistentStore):
    _instance: CommandOptionStore | None = None
    _initialized = False
    _default_path: Path | None = None

    @classmethod
    def instance(cls) -> CommandOptionStore:
        if cls._instance is None:
            inst = object.__new__(cls)
            PersistentStore.__init__(inst, cls._default_path)
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
