from wafer.builtins.registration import register_all
from wafer.plugin.registry import PluginBase, PluginRegistry, FilePluginRegistry, CommandGroupRegistry
from wafer.plugin.grid.handler import grid_resolver
from wafer.plugin.viewer.handler import viewer_resolver
from wafer.plugin.collector.handler import collector_resolver
from wafer.plugin.query.handler import filter_registry, sort_registry
from wafer.plugin.layout.handler import layout_registry
from wafer.plugin.panel.handler import panel_registry
from wafer.plugin.rename.handler import rename_source_registry
from wafer.plugin.imageloader.handler import image_loader_resolver


class TestBuiltinImageLoaderRegistration:
    def test_system_thumbnail_registered(self):
        assert "system_thumbnail" in image_loader_resolver.registry.names()

    def test_system_thumbnail_is_fallback(self):
        all_plugins = image_loader_resolver.registry.list_all()
        assert all_plugins[-1].NAME == "system_thumbnail"

    def test_system_thumbnail_matches_any_extension(self):
        cls = image_loader_resolver.registry.get("system_thumbnail")
        assert cls.EXTENSIONS == () or cls.match("test.xyz")


class TestBuiltinViewerRegistration:
    def test_default_viewer_registered(self):
        assert "default_viewer" in viewer_resolver.registry.names()

    def test_default_viewer_is_fallback(self):
        all_plugins = viewer_resolver.registry.list_all()
        assert all_plugins[-1].NAME == "default_viewer"


class TestBuiltinFilterRegistration:
    BUILTIN_FILTERS = {"text", "directory", "date_range"}

    def test_all_builtin_filters_registered(self):
        names = set(filter_registry.names())
        assert self.BUILTIN_FILTERS.issubset(names)

    def test_text_filter_higher_than_directory(self):
        all_filters = filter_registry.list_all()
        names = [f.NAME for f in all_filters]
        text_idx = names.index("text")
        dir_idx = names.index("directory")
        assert text_idx < dir_idx


class TestBuiltinSortRegistration:
    BUILTIN_SORTS = {"path", "name", "modified", "created", "size", "collected", "random"}

    def test_all_builtin_sorts_registered(self):
        names = set(sort_registry.names())
        assert self.BUILTIN_SORTS.issubset(names)

    def test_priority_ordering_consistent(self):
        all_sorts = sort_registry.list_all()
        for i in range(len(all_sorts) - 1):
            assert all_sorts[i].PRIORITY >= all_sorts[i + 1].PRIORITY


class TestBuiltinLayoutRegistration:
    BUILTIN_LAYOUTS = {"justified", "masonry", "multiSpan", "multiSpanTiling"}

    def test_all_builtin_layouts_registered(self):
        names = set(layout_registry.names())
        assert self.BUILTIN_LAYOUTS.issubset(names)


class TestBuiltinPanelRegistration:
    BUILTIN_PANELS = {"database_manager", "batch_renamer", "plugin_manager"}

    def test_all_builtin_panels_registered(self):
        names = set(panel_registry.names())
        assert self.BUILTIN_PANELS.issubset(names)


class TestBuiltinRenameSourceRegistration:
    BUILTIN_SOURCES = {"name", "fixed", "seq", "datetime", "meta", "random", "ext"}

    def test_all_builtin_rename_sources_registered(self):
        names = set(rename_source_registry.names())
        assert self.BUILTIN_SOURCES.issubset(names)


class TestResolveChainWithBuiltins:
    def test_unknown_ext_falls_to_system_thumbnail(self):
        chain = grid_resolver.resolve_merged_chain("test.xyz_unknown")
        names = [p.NAME for p, kind in chain]
        assert "system_thumbnail" in names

    def test_jpg_resolves_image_and_fallback(self):
        chain = grid_resolver.resolve_merged_chain("test.jpg")
        names = [p.NAME for p, kind in chain]
        assert "image" in names
        assert "system_thumbnail" in names
        assert names.index("image") < names.index("system_thumbnail")

    def test_viewer_unknown_ext_falls_to_default(self):
        chain = viewer_resolver.registry.resolve_chain("test.xyz_unknown")
        names = [p.NAME for p in chain]
        assert "default_viewer" in names


class TestBuiltinNameUniqueness:
    def test_no_duplicate_names_across_registries(self):
        all_registries = {
            "grid": grid_resolver.registry,
            "viewer": viewer_resolver.registry,
            "filter": filter_registry,
            "sort": sort_registry,
            "layout": layout_registry,
            "panel": panel_registry,
            "rename_source": rename_source_registry,
        }
        for reg_name, registry in all_registries.items():
            names = registry.names()
            assert len(names) == len(set(names)), f"Duplicates in {reg_name}: {names}"
