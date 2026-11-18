from __future__ import annotations

import contextlib
import json
import os
from collections.abc import Iterator
from configparser import ConfigParser, Error as ConfigParserError
from typing import Any

from ..core.common.ini_io import write_ini
from ..core.common.paths import resolve_data_path
from ..core.logs import AppLogger
from ..core.platform.process_lock import file_lock

_INI_FILENAME = "viewer_plugins.ini"


def _ini_path() -> str:
    return resolve_data_path(_INI_FILENAME)


def _read_unlocked(path: str) -> ConfigParser:
    cp = ConfigParser()
    if not os.path.isfile(path):
        return cp
    try:
        cp.read(path, encoding="utf-8")
    except ConfigParserError as e:
        AppLogger.warning(f"[PluginConfig] {path} is unreadable, using defaults ({e})", exc=e)
        return ConfigParser()
    return cp


def read_ini() -> ConfigParser:
    path = _ini_path()
    with file_lock(f"{path}.lock"):
        return _read_unlocked(path)


@contextlib.contextmanager
def update_ini() -> Iterator[ConfigParser]:
    path = _ini_path()
    with file_lock(f"{path}.lock"):
        cp = _read_unlocked(path)
        yield cp
        write_ini(path, cp)


def format_ini_value(value: Any) -> str:
    if isinstance(value, bool):
        return json.dumps(value)
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, set):
        return json.dumps(sorted(value), ensure_ascii=False)
    return str(value)


class PluginConfig:
    def __init__(self, section: str, defaults: dict[str, Any]):
        self._section = section
        self._defaults = dict(defaults)
        self._cache: dict[str, Any] = {}

    def load(self) -> dict[str, Any]:
        self._cache = self._values_in(read_ini())
        return dict(self._cache)

    def _values_in(self, cp: ConfigParser) -> dict[str, Any]:
        result = dict(self._defaults)
        if not cp.has_section(self._section):
            return result
        for key, default in self._defaults.items():
            raw = cp.get(self._section, key, fallback=None)
            if raw is not None:
                result[key] = _cast(raw, default)
        return result

    def get(self, key: str) -> Any:
        if not self._cache:
            self.load()
        return self._cache.get(key, self._defaults.get(key))

    def to_dict(self) -> dict[str, Any]:
        if not self._cache:
            self.load()
        return dict(self._cache)

    def save(self, **values: Any) -> None:
        with update_ini() as cp:
            if not cp.has_section(self._section):
                cp.add_section(self._section)
            for key, value in values.items():
                cp.set(self._section, key, format_ini_value(value))
        self._cache = {**self._values_in(cp), **values}

    def save_and_notify(self, collector_name: str, **values: Any) -> None:
        self.save(**values)
        from .collector.base import BaseCollector

        BaseCollector.notify_to(collector_name, payload=values or None)


def _cast(raw: str, default: Any) -> Any:
    if isinstance(default, bool):
        if raw.lower() in ("true", "1", "yes"):
            return True
        if raw.lower() in ("false", "0", "no"):
            return False
        try:
            return bool(json.loads(raw))
        except (json.JSONDecodeError, TypeError, ValueError):
            return default
    if isinstance(default, int):
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default
    if isinstance(default, float):
        try:
            return float(raw)
        except (TypeError, ValueError):
            return default
    if isinstance(default, (dict, list)):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return default
    return raw
