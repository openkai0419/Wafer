import json
import os
from configparser import ConfigParser

_INI_FILENAME = "viewer_plugins.ini"
_SECTION = "exiftool"
_MODE_KEY = "filter_mode"
_KEYS_KEY = "filter_keys"

MODE_BLACKLIST = "blacklist"
MODE_WHITELIST = "whitelist"


def _ini_path() -> str:
    from wafer.utils.paths import resolve_data_path

    return resolve_data_path(_INI_FILENAME)


def read_filter_config() -> tuple[str, set[str]]:
    path = _ini_path()
    if not os.path.isfile(path):
        return MODE_BLACKLIST, set()
    cp = ConfigParser()
    cp.read(path, encoding="utf-8")
    mode = cp.get(_SECTION, _MODE_KEY, fallback=MODE_BLACKLIST)
    if mode not in (MODE_BLACKLIST, MODE_WHITELIST):
        mode = MODE_BLACKLIST
    raw = cp.get(_SECTION, _KEYS_KEY, fallback=None)
    if raw is None:
        raw = cp.get(_SECTION, "blacklist", fallback=None)
    if raw is None:
        return mode, set()
    try:
        val = json.loads(raw)
        if isinstance(val, list):
            return mode, set(val)
    except (json.JSONDecodeError, TypeError):
        pass
    return mode, set()


def write_filter_config(mode: str, keys: set[str]):
    path = _ini_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    cp = ConfigParser()
    if os.path.isfile(path):
        cp.read(path, encoding="utf-8")
    if not cp.has_section(_SECTION):
        cp.add_section(_SECTION)
    cp.set(_SECTION, _MODE_KEY, mode)
    cp.set(_SECTION, _KEYS_KEY, json.dumps(sorted(keys), ensure_ascii=False))
    if cp.has_option(_SECTION, "blacklist"):
        cp.remove_option(_SECTION, "blacklist")
    with open(path, "w", encoding="utf-8") as f:
        cp.write(f)


_SORT_MODE_KEY = "sort_mode"
_SORT_ASC_KEY = "sort_ascending"

SORT_NAME = 0
SORT_COUNT = 1


def read_sort_config() -> tuple[int, bool]:
    path = _ini_path()
    if not os.path.isfile(path):
        return SORT_COUNT, False
    cp = ConfigParser()
    cp.read(path, encoding="utf-8")
    raw_mode = cp.get(_SECTION, _SORT_MODE_KEY, fallback="count")
    mode = SORT_NAME if raw_mode == "name" else SORT_COUNT
    raw_asc = cp.get(_SECTION, _SORT_ASC_KEY, fallback="false")
    ascending = raw_asc.lower() == "true"
    return mode, ascending


def write_sort_config(mode: int, ascending: bool):
    path = _ini_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    cp = ConfigParser()
    if os.path.isfile(path):
        cp.read(path, encoding="utf-8")
    if not cp.has_section(_SECTION):
        cp.add_section(_SECTION)
    cp.set(_SECTION, _SORT_MODE_KEY, "name" if mode == SORT_NAME else "count")
    cp.set(_SECTION, _SORT_ASC_KEY, "true" if ascending else "false")
    with open(path, "w", encoding="utf-8") as f:
        cp.write(f)
