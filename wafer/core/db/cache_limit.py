from __future__ import annotations

import threading
from configparser import ConfigParser
from configparser import Error as ConfigError
from functools import lru_cache

from ..common.ini_io import write_ini
from ..common.paths import resolve_data_path
from ..logs import AppLogger

_FILENAME = "cache_settings.ini"
_SECTION = "database"
_OPTION = "cache_limit_mb"

DB_CACHE_DEFAULT_MB = 512

_lock = threading.Lock()


def _read() -> ConfigParser:
    cp = ConfigParser()
    try:
        cp.read(resolve_data_path(_FILENAME), encoding="utf-8")
    except (ConfigError, UnicodeDecodeError) as exc:
        AppLogger.warning(f"{_FILENAME} is damaged, using the default SQLite cache limit. Saving Cache Limits rewrites it.", exc=exc)
        return ConfigParser()
    return cp


def db_cache_limit_mb() -> int:
    try:
        return _read().getint(_SECTION, _OPTION, fallback=DB_CACHE_DEFAULT_MB)
    except ValueError:
        return DB_CACHE_DEFAULT_MB


@lru_cache(maxsize=1)
def process_db_cache_limit_mb() -> int:
    return db_cache_limit_mb()


def save_db_cache_limit(limit_mb: int) -> None:
    with _lock:
        cp = _read()
        if not cp.has_section(_SECTION):
            cp.add_section(_SECTION)
        cp.set(_SECTION, _OPTION, str(int(limit_mb)))
        write_ini(resolve_data_path(_FILENAME), cp)
