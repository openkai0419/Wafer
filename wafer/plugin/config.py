from __future__ import annotations

import json
import os
import threading
from configparser import ConfigParser
from typing import Any

from ..utils.paths import resolve_data_path

_INI_FILENAME = "viewer_plugins.ini"

ini_lock = threading.Lock()


def _ini_path() -> str:
    return resolve_data_path(_INI_FILENAME)


class PluginConfig:
    def __init__(self, section: str, defaults: dict[str, Any]):
        self._section = section
        self._defaults = dict(defaults)
        self._cache: dict[str, Any] = {}

    def load(self) -> dict[str, Any]:
        with ini_lock:
            path = _ini_path()
            result = dict(self._defaults)
            if not os.path.isfile(path):
                self._cache = dict(result)
                return dict(result)
            cp = ConfigParser()
            cp.read(path, encoding="utf-8")
            if not cp.has_section(self._section):
                self._cache = dict(result)
                return dict(result)
            for key, default in self._defaults.items():
                raw = cp.get(self._section, key, fallback=None)
                if raw is None:
                    continue
                result[key] = _cast(raw, default)
            self._cache = dict(result)
            return dict(result)

    def get(self, key: str) -> Any:
        if not self._cache:
            self.load()
        return self._cache.get(key, self._defaults.get(key))

    def to_dict(self) -> dict[str, Any]:
        if not self._cache:
            self.load()
        return dict(self._cache)

    def save(self, **values: Any) -> None:
        with ini_lock:
            path = _ini_path()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            cp = ConfigParser()
            if os.path.isfile(path):
                cp.read(path, encoding="utf-8")
            if not cp.has_section(self._section):
                cp.add_section(self._section)
            merged = dict(self._cache) if self._cache else dict(self._defaults)
            merged.update(values)
            for key, value in merged.items():
                if isinstance(value, (dict, list, tuple, set)):
                    cp.set(self._section, key, json.dumps(value, ensure_ascii=False))
                elif isinstance(value, bool):
                    cp.set(self._section, key, json.dumps(value))
                else:
                    cp.set(self._section, key, str(value))
            with open(path, "w", encoding="utf-8") as f:
                cp.write(f)
            self._cache = merged

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
