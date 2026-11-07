from __future__ import annotations

import os
import threading
from configparser import ConfigParser

from ..common.paths import resolve_data_path

_FILENAME = "cache_settings.ini"
_SECTION = "database"
_OPTION = "cache_limit_mb"

DB_CACHE_DEFAULT_MB = 512

_lock = threading.Lock()


def _read() -> ConfigParser:
    cp = ConfigParser()
    path = resolve_data_path(_FILENAME)
    if os.path.isfile(path):
        cp.read(path, encoding="utf-8")
    return cp


def db_cache_limit_mb() -> int:
    try:
        return _read().getint(_SECTION, _OPTION, fallback=DB_CACHE_DEFAULT_MB)
    except ValueError:
        return DB_CACHE_DEFAULT_MB


def save_db_cache_limit(limit_mb: int) -> None:
    with _lock:
        cp = _read()
        if not cp.has_section(_SECTION):
            cp.add_section(_SECTION)
        cp.set(_SECTION, _OPTION, str(int(limit_mb)))
        path = resolve_data_path(_FILENAME)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            cp.write(f)
