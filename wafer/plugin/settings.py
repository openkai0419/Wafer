from ..core.common.helpers import try_json_loads
from .config import format_ini_value, read_ini, update_ini
from .installer import RestartScope
from . import installer_queue


def _split_key(key: str) -> tuple[str, str]:
    section, _, option = key.partition("/")
    if not option:
        return "General", section
    return section, option


def _read_ini_value(key: str, default=None):
    section, option = _split_key(key)
    raw = read_ini().get(section, option, fallback=None)
    if raw is None:
        return default
    return try_json_loads(raw, raw)


def _write_ini_value(key: str, value):
    section, option = _split_key(key)
    with update_ini() as cp:
        if not cp.has_section(section):
            cp.add_section(section)
        cp.set(section, option, format_ini_value(value))


def default_enabled_per_db(cls) -> bool:
    per_db = getattr(cls, "DEFAULT_ENABLED_PER_DB", None)
    if per_db is not None:
        return bool(per_db)
    return bool(getattr(cls, "DEFAULT_ENABLED", False))


class PluginSettings:
    def enabled_overrides(self) -> dict[str, bool]:
        val = _read_ini_value("plugins/enabled_overrides")
        if not isinstance(val, dict):
            return {}
        return {str(k): v for k, v in val.items() if isinstance(v, bool)}

    def set_enabled_overrides(self, overrides: dict[str, bool]):
        clean = {str(k): bool(v) for k, v in sorted(overrides.items())}
        _write_ini_value("plugins/enabled_overrides", clean)

    def active_folders(self) -> list[str]:
        val = _read_ini_value("plugins/active_folders")
        return [str(f) for f in val] if isinstance(val, list) else []

    def set_active_folders(self, folders):
        _write_ini_value("plugins/active_folders", sorted(set(folders)))

    def is_plugin_enabled(
        self,
        qualified_name: str,
        plugin_cls: type,
        overrides: dict[str, bool] | None = None,
    ) -> bool:
        if overrides is None:
            overrides = self.enabled_overrides()
        return self.resolve_enabled(qualified_name, plugin_cls, overrides)

    @staticmethod
    def resolve_enabled(
        qualified_name: str,
        plugin_cls: type,
        overrides: dict[str, bool] | None = None,
    ) -> bool:
        overrides = overrides or {}
        if qualified_name in overrides:
            return bool(overrides[qualified_name])
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
            if default_enabled_per_db(cls):
                defaults.append(name)
        for name in parser_resolver.names():
            cls = parser_resolver.registry.get(name)
            if default_enabled_per_db(cls):
                defaults.append(name)
        return defaults
