import json
import os
from configparser import ConfigParser

_INI_FILENAME = "viewer_plugins.ini"
_SECTION = "exif"
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
