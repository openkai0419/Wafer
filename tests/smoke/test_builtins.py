import inspect

from wafer.builtins.registration import register_all, _discover_builtins, _import_builtin_modules
from wafer.plugin.loader import _get_registry_map
from wafer.plugin.registry import PluginBase


class TestBuiltinModuleDiscovery:
    def test_import_builtin_modules_returns_modules(self):
        modules = _import_builtin_modules()
        assert len(modules) > 0
        for mod in modules:
            assert inspect.ismodule(mod)

    def test_discover_builtins_finds_plugins(self):
        registry_map = _get_registry_map()
        modules = _import_builtin_modules()
        all_found = []
        for mod in modules:
            all_found.extend(_discover_builtins(mod, registry_map))
        assert len(all_found) > 0

    def test_discovered_builtins_are_pluginbase_subclass(self):
        registry_map = _get_registry_map()
        modules = _import_builtin_modules()
        for mod in modules:
            for registry_key, cls in _discover_builtins(mod, registry_map):
                assert issubclass(cls, PluginBase), f"{cls.__name__} is not PluginBase"

    def test_discovered_builtins_have_name(self):
        registry_map = _get_registry_map()
        modules = _import_builtin_modules()
        for mod in modules:
            for registry_key, cls in _discover_builtins(mod, registry_map):
                if registry_key != "command":
                    assert cls.NAME, f"{cls.__name__} has no NAME"

    def test_discovered_builtins_have_int_priority(self):
        registry_map = _get_registry_map()
        modules = _import_builtin_modules()
        for mod in modules:
            for registry_key, cls in _discover_builtins(mod, registry_map):
                assert isinstance(cls.PRIORITY, int), f"{cls.__name__}.PRIORITY is not int"


class TestBuiltinNAMEUniqueness:
    def test_names_unique_per_registry_key(self):
        registry_map = _get_registry_map()
        modules = _import_builtin_modules()
        seen: dict[str, dict[str, str]] = {}
        for mod in modules:
            for registry_key, cls in _discover_builtins(mod, registry_map):
                if registry_key == "command":
                    continue
                bucket = seen.setdefault(registry_key, {})
                assert cls.NAME not in bucket, f"Duplicate NAME '{cls.NAME}' in registry '{registry_key}': {bucket[cls.NAME]} vs {cls.__name__}"
                bucket[cls.NAME] = cls.__name__

    def test_valid_registry_keys(self):
        valid_keys = {"viewer", "grid", "grid_overlay", "collector", "parser", "filter", "sort", "layout", "panel", "key_value_panel", "rename_source", "command", "imageloader"}
        registry_map = _get_registry_map()
        modules = _import_builtin_modules()
        for mod in modules:
            for registry_key, cls in _discover_builtins(mod, registry_map):
                assert registry_key in valid_keys, f"{cls.__name__} has invalid registry_key: {registry_key}"


class TestBuiltinExpectedPlugins:
    EXPECTED_GRID: set[str] = set()
    EXPECTED_GRID_OVERLAY = {"mark_overlay"}
    EXPECTED_IMAGELOADER = {"system_thumbnail"}
    EXPECTED_VIEWER = {"default_viewer"}
    EXPECTED_FILTER = {"text", "directory"}
    EXPECTED_SORT = {"path", "name", "modified", "created", "size", "collected", "random"}
    EXPECTED_LAYOUT = {"justified", "masonry"}
    EXPECTED_PANEL = {"database_manager", "batch_renamer", "plugin_manager"}
    EXPECTED_RENAME = {"name", "fixed", "seq", "datetime", "meta", "random", "ext"}

    def _collect_names_by_key(self):
        registry_map = _get_registry_map()
        modules = _import_builtin_modules()
        by_key: dict[str, set[str]] = {}
        for mod in modules:
            for registry_key, cls in _discover_builtins(mod, registry_map):
                by_key.setdefault(registry_key, set()).add(cls.NAME)
        return by_key

    def test_expected_imageloader_builtins(self):
        by_key = self._collect_names_by_key()
        assert self.EXPECTED_IMAGELOADER.issubset(by_key.get("imageloader", set()))

    def test_expected_grid_overlay_builtins(self):
        by_key = self._collect_names_by_key()
        assert self.EXPECTED_GRID_OVERLAY.issubset(by_key.get("grid_overlay", set()))

    def test_expected_viewer_builtins(self):
        by_key = self._collect_names_by_key()
        assert self.EXPECTED_VIEWER.issubset(by_key.get("viewer", set()))

    def test_expected_filter_builtins(self):
        by_key = self._collect_names_by_key()
        assert self.EXPECTED_FILTER.issubset(by_key.get("filter", set()))

    def test_expected_sort_builtins(self):
        by_key = self._collect_names_by_key()
        assert self.EXPECTED_SORT.issubset(by_key.get("sort", set()))

    def test_expected_layout_builtins(self):
        by_key = self._collect_names_by_key()
        assert self.EXPECTED_LAYOUT.issubset(by_key.get("layout", set()))

    def test_expected_panel_builtins(self):
        by_key = self._collect_names_by_key()
        assert self.EXPECTED_PANEL.issubset(by_key.get("panel", set()))

    def test_expected_rename_source_builtins(self):
        by_key = self._collect_names_by_key()
        assert self.EXPECTED_RENAME.issubset(by_key.get("rename_source", set()))
