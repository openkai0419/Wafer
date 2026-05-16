import json
import os
from configparser import ConfigParser
from ..utils.paths import resolve_data_path
from ..utils.helpers import try_json_loads
from .config import ini_lock
from .installer import RestartScope
from . import installer_queue


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
    with ini_lock:
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
    def has_enabled_overrides(self) -> bool:
        return isinstance(_read_ini_value("plugins/enabled_overrides"), dict)

    def enabled_overrides(self) -> dict[str, bool]:
        val = _read_ini_value("plugins/enabled_overrides")
        if not isinstance(val, dict):
            return {}
        return {str(k): v for k, v in val.items() if isinstance(v, bool)}

    def set_enabled_overrides(self, overrides: dict[str, bool]):
        clean = {str(k): bool(v) for k, v in sorted(overrides.items())}
        _write_ini_value("plugins/enabled_overrides", clean)

    def enabled_names(self) -> set[str] | None:
        val = _read_ini_value("plugins/enabled")
        if isinstance(val, list):
            return set(val)
        return None

    def set_enabled(self, names: set[str]):
        _write_ini_value("plugins/enabled", sorted(names))

    def is_plugin_enabled(
        self,
        qualified_name: str,
        plugin_cls: type,
        overrides: dict[str, bool] | None = None,
        legacy_enabled: set[str] | None = None,
    ) -> bool:
        if overrides is None:
            overrides = self.enabled_overrides()
            if legacy_enabled is None and not self.has_enabled_overrides():
                legacy_enabled = self.enabled_names()
        return self.resolve_enabled(qualified_name, plugin_cls, overrides, legacy_enabled)

    @staticmethod
    def resolve_enabled(
        qualified_name: str,
        plugin_cls: type,
        overrides: dict[str, bool] | None = None,
        legacy_enabled: set[str] | None = None,
    ) -> bool:
        overrides = overrides or {}
        if qualified_name in overrides:
            return bool(overrides[qualified_name])
        if legacy_enabled is not None:
            return qualified_name in legacy_enabled
        return bool(getattr(plugin_cls, "DEFAULT_ENABLED", False))

    @staticmethod
    def enabled_override(qualified_name: str, plugin_cls: type, enabled: bool) -> tuple[str, bool] | None:
        enabled = bool(enabled)
        if enabled == bool(getattr(plugin_cls, "DEFAULT_ENABLED", False)):
            return None
        return qualified_name, enabled

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

    def restart_scope(self) -> RestartScope:
        val = _read_ini_value("plugins/restart_scope")
        if isinstance(val, list):
            scope = RestartScope.NONE
            for s in val:
                if s == "viewer":
                    scope |= RestartScope.VIEWER
                elif s == "tray":
                    scope |= RestartScope.TRAY
            return scope
        if str(_read_ini_value("plugins/restart_pending", False)).lower() == "true":
            return RestartScope.ALL
        return RestartScope.NONE

    def set_restart_scope(self, scope: RestartScope):
        parts: list[str] = []
        if RestartScope.VIEWER in scope:
            parts.append("viewer")
        if RestartScope.TRAY in scope:
            parts.append("tray")
        _write_ini_value("plugins/restart_scope", parts)

    def merge_restart_scope(self, scope: RestartScope):
        self.set_restart_scope(self.restart_scope() | scope)

    def clear_restart_scope(self):
        self.set_restart_scope(RestartScope.NONE)

    def needs_restart(self, extensions_dir: str) -> RestartScope:
        scope = self.restart_scope()
        if installer_queue.has_pending_queue(extensions_dir):
            scope |= RestartScope.ALL
        return scope

    def resolve_default_collectors(self) -> list[str]:
        saved = self.default_enabled_collectors()
        if saved is not None:
            return saved
        from .collector.handler import collector_resolver
        from .parser.handler import parser_resolver

        defaults = []
        for name in collector_resolver.names():
            cls = collector_resolver.registry.get(name)
            if getattr(cls, "DEFAULT_ENABLED", False):
                defaults.append(name)
        for name in parser_resolver.names():
            cls = parser_resolver.registry.get(name)
            if getattr(cls, "DEFAULT_ENABLED", False):
                defaults.append(name)
        return defaults
