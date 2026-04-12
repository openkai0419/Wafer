import json
import os
from configparser import ConfigParser
from ..utils.paths import resolve_data_path
from ..utils.helpers import try_json_loads


_INI_FILENAME = "viewer_plugins.ini"


def _ini_path() -> str:
    return resolve_data_path(_INI_FILENAME)


def _read_ini_value(key: str, default=None):
    path = _ini_path()
    if not os.path.isfile(path):
        return default
    cp = ConfigParser()
    cp.read(path, encoding="utf-8")
    section, _, option = key.partition("/")
    if not option:
        section, option = "General", section
    if not cp.has_section(section):
        return default
    raw = cp.get(section, option, fallback=None)
    if raw is None:
        return default
    return try_json_loads(raw, raw)


def _write_ini_value(key: str, value):
    path = _ini_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    cp = ConfigParser()
    if os.path.isfile(path):
        cp.read(path, encoding="utf-8")
    section, _, option = key.partition("/")
    if not option:
        section, option = "General", section
    if not cp.has_section(section):
        cp.add_section(section)
    if isinstance(value, (dict, list, tuple)):
        cp.set(section, option, json.dumps(value, ensure_ascii=False))
    else:
        cp.set(section, option, str(value))
    with open(path, "w", encoding="utf-8") as f:
        cp.write(f)


class PluginSettings:
    def enabled_names(self) -> set[str] | None:
        val = _read_ini_value("plugins/enabled")
        if isinstance(val, list):
            return set(val)
        return None

    def set_enabled(self, names: set[str]):
        _write_ini_value("plugins/enabled", sorted(names))

    def priority_order(self, key: str) -> list[str]:
        val = _read_ini_value(f"priority/{key}")
        if isinstance(val, list):
            return val
        val = _read_ini_value(f"plugins/{key}_order")
        if isinstance(val, list):
            return val
        return []

    def set_priority_order(self, key: str, order: list[str]):
        _write_ini_value(f"priority/{key}", order)

    def default_enabled_collectors(self) -> list[str] | None:
        val = _read_ini_value("collectors/default_enabled")
        if isinstance(val, list):
            return val
        return None

    def set_default_enabled_collectors(self, names: list[str]):
        _write_ini_value("collectors/default_enabled", sorted(names))

    def resolve_default_collectors(self) -> list[str]:
        saved = self.default_enabled_collectors()
        if saved is not None:
            return saved
        from .collector.handler import collector_resolver
        from .detacher.handler import detacher_resolver

        defaults = []
        for name in collector_resolver.names():
            cls = collector_resolver.registry.get(name)
            if getattr(cls, "DEFAULT_ENABLED", False):
                defaults.append(name)
        for name in detacher_resolver.names():
            cls = detacher_resolver.registry.get(name)
            if getattr(cls, "DEFAULT_ENABLED", False):
                defaults.append(name)
        return defaults
