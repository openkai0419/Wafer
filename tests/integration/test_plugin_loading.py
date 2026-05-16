import os
from unittest.mock import patch

import pytest

from wafer.plugin.loader import (
    PluginLoader,
    _import_extension,
    get_plugin_dir,
    qualify_plugin_name,
)
from wafer.plugin.registry import (
    PluginRegistry,
    FilePluginRegistry,
    CommandGroupRegistry,
    PluginBase,
)
from wafer.plugin.grid.handler import grid_resolver
from wafer.plugin.viewer.handler import viewer_resolver
from wafer.plugin.collector.handler import collector_resolver
from wafer.plugin.parser.handler import parser_resolver
from wafer.plugin.query.handler import filter_registry, sort_registry
from wafer.plugin.layout.handler import layout_registry
from wafer.plugin.panel.handler import panel_registry
from wafer.plugin.rename.handler import rename_source_registry
from wafer.plugin.imageloader.handler import image_loader_resolver


EXTENSIONS_DIR = get_plugin_dir()


class TestGridRegistryState:
    def test_animated_plugin_registered(self):
        assert "animated" in grid_resolver.registry.names()

    def test_video_plugin_registered(self):
        assert "video" in grid_resolver.registry.names()


class TestImageLoaderRegistryState:
    def test_image_loader_registered(self):
        assert "image" in image_loader_resolver.registry.names()

    def test_system_thumbnail_fallback_registered(self):
        assert "system_thumbnail" in image_loader_resolver.registry.names()

    def test_image_before_system_in_priority(self):
        all_plugins = image_loader_resolver.registry.list_all()
        names_in_order = [p.NAME for p in all_plugins]
        image_idx = names_in_order.index("image")
        sys_idx = names_in_order.index("system_thumbnail")
        assert image_idx < sys_idx

    def test_system_thumbnail_last_in_priority(self):
        all_plugins = image_loader_resolver.registry.list_all()
        assert all_plugins[-1].NAME == "system_thumbnail"


class TestViewerRegistryState:
    def test_animated_viewer_registered(self):
        assert "animated" in viewer_resolver.registry.names()

    def test_video_viewer_registered(self):
        assert "video" in viewer_resolver.registry.names()

    def test_image_registered_as_builtin_fallback_viewer(self):
        assert "image" in viewer_resolver.registry.names()

    def test_default_viewer_removed(self):
        assert "default_viewer" not in viewer_resolver.registry.names()


class TestPathResolutionRegistryState:
    def test_zip_resolution_plugins_registered(self):
        assert "zip" in viewer_resolver.registry.names()
        assert "zip" in grid_resolver.registry.names()
        assert "zip" in image_loader_resolver.registry.names()


class TestCollectorRegistryState:
    def test_exif_collector_registered(self):
        assert "exiftool" in collector_resolver.names()

    def test_wd14_not_registered_by_default(self):
        assert "wd14" not in collector_resolver.names()


class TestParserRegistryState:
    def test_novelai_not_registered_by_default(self):
        assert "novelai" not in parser_resolver.names()


class TestFilterRegistryState:
    def test_text_filter_registered(self):
        assert "text" in filter_registry.names()

    def test_directory_filter_registered(self):
        assert "directory" in filter_registry.names()

    def test_date_range_filter_registered(self):
        assert "date_range" in filter_registry.names()

    def test_regex_filter_registered(self):
        assert "regex" in filter_registry.names()

    def test_builtin_priority_values(self):
        assert filter_registry.get("text").PRIORITY > filter_registry.get("directory").PRIORITY

    def test_extension_priority_values(self):
        assert filter_registry.get("regex").PRIORITY > filter_registry.get("date_range").PRIORITY


class TestSortRegistryState:
    EXPECTED_SORTS = {"path", "name", "modified", "created", "size", "collected", "random"}

    def test_all_sorts_registered(self):
        registered = set(sort_registry.names())
        assert self.EXPECTED_SORTS.issubset(registered)

    def test_priority_ordering(self):
        all_plugins = sort_registry.list_all()
        for i in range(len(all_plugins) - 1):
            assert all_plugins[i].PRIORITY >= all_plugins[i + 1].PRIORITY


class TestLayoutRegistryState:
    def test_justified_layout_registered(self):
        assert "justified" in layout_registry.names()

    def test_masonry_layout_registered(self):
        assert "masonry" in layout_registry.names()

    def test_multispan_layout_registered(self):
        assert "multiSpan" in layout_registry.names()

    def test_multispan_tiling_layout_registered(self):
        assert "multiSpanTiling" in layout_registry.names()

    def test_optional_layouts_not_loaded_by_default(self):
        names = layout_registry.names()
        assert "optimizedJustified" not in names
        assert "ratioPartition" not in names


class TestPanelRegistryState:
    def test_database_manager_registered(self):
        assert "database_manager" in panel_registry.names()

    def test_batch_renamer_registered(self):
        assert "batch_renamer" in panel_registry.names()

    def test_plugin_manager_registered(self):
        assert "plugin_manager" in panel_registry.names()


class TestRenameSourceRegistryState:
    EXPECTED_SOURCES = {"name", "fixed", "seq", "datetime", "meta", "random", "ext"}

    def test_all_sources_registered(self):
        registered = set(rename_source_registry.names())
        assert self.EXPECTED_SOURCES.issubset(registered)


class TestResolutionChainOrder:
    def test_gif_merged_chain_animated_first(self):
        chain = grid_resolver.resolve_merged_chain("test.gif")
        names = [cls.NAME for cls, kind in chain]
        assert "animated" in names
        assert "image" in names
        assert names.index("animated") < names.index("image")

    def test_webp_merged_chain_animated_first(self):
        chain = grid_resolver.resolve_merged_chain("test.webp")
        names = [cls.NAME for cls, kind in chain]
        assert "animated" in names
        assert "image" in names
        assert names.index("animated") < names.index("image")

    def test_jpg_merged_chain_no_animated(self):
        chain = grid_resolver.resolve_merged_chain("test.jpg")
        names = [cls.NAME for cls, kind in chain]
        assert "image" in names
        assert "animated" not in names

    def test_mp4_merged_chain_video_present(self):
        chain = grid_resolver.resolve_merged_chain("test.mp4")
        names = [cls.NAME for cls, kind in chain]
        assert "video" in names
        assert "image" not in names

    def test_unknown_merged_chain_fallback_only(self):
        chain = grid_resolver.resolve_merged_chain("test.xyz_unknown")
        names = [cls.NAME for cls, kind in chain]
        assert names[-1] == "system_thumbnail"
        assert "image" not in names
        assert "animated" not in names

    def test_viewer_gif_chain_animated_first(self):
        chain = viewer_resolver.registry.resolve_chain("test.gif")
        names = [p.NAME for p in chain]
        assert "animated" in names
        assert "image" in names
        assert names.index("animated") < names.index("image")


class TestPluginLoaderFreshLoad:
    def _make_fresh_registries(self):
        return {
            "viewer": FilePluginRegistry(),
            "grid": FilePluginRegistry(),
            "collector": PluginRegistry(),
            "parser": PluginRegistry(),
            "filter": PluginRegistry(),
            "sort": PluginRegistry(),
            "layout": PluginRegistry(),
            "panel": PluginRegistry(),
            "rename_source": PluginRegistry(),
            "imageloader": FilePluginRegistry(),
            "resolver": FilePluginRegistry(),
            "command": CommandGroupRegistry(),
        }

    def test_load_all_returns_loaded_extension_names(self):
        registries = self._make_fresh_registries()
        loader = PluginLoader(EXTENSIONS_DIR, registries, enabled=None)
        loaded = loader.load_all()
        assert isinstance(loaded, list)
        for name in ("image", "video", "animated", "additional_filters"):
            assert name in loaded, f"{name} should be loaded"

    def test_disabled_by_default_not_loaded(self):
        registries = self._make_fresh_registries()
        loader = PluginLoader(EXTENSIONS_DIR, registries, enabled=None)
        loader.load_all()
        assert "wd14" not in registries["collector"].names()
        assert "novelai" not in registries["parser"].names()

    def test_enabled_override_false_disables_default_enabled_plugin(self):
        registries = self._make_fresh_registries()
        folder = os.path.join(EXTENSIONS_DIR, "image")
        found = _import_extension("image", folder)
        overrides = {}
        for rk, cls in found:
            if cls.__name__ == "ImageFileLoader":
                overrides[qualify_plugin_name(rk, cls)] = False
        loader = PluginLoader(EXTENSIONS_DIR, registries, enabled=overrides)
        loader.load_all()
        assert "image" not in registries["imageloader"].names()
        assert "zip" in registries["viewer"].names()

    def test_alphabetical_load_order(self):
        registries = self._make_fresh_registries()
        loader = PluginLoader(EXTENSIONS_DIR, registries, enabled=None)
        loaded = loader.load_all()
        assert loaded == sorted(loaded)

    def test_nonexistent_plugin_dir_returns_empty(self):
        registries = self._make_fresh_registries()
        loader = PluginLoader("/nonexistent_path_xyz", registries, enabled=None)
        loaded = loader.load_all()
        assert loaded == []


class TestPluginPriorityOverride:
    def test_higher_priority_wins_registration(self):
        registry = PluginRegistry()

        class PluginA(PluginBase):
            NAME = "_test_override"
            PRIORITY = 10

        class PluginB(PluginBase):
            NAME = "_test_override"
            PRIORITY = 50

        registry.register(PluginA)
        registry.register(PluginB)
        assert registry.get("_test_override") is PluginB

    def test_lower_priority_rejected(self):
        registry = PluginRegistry()

        class PluginA(PluginBase):
            NAME = "_test_reject"
            PRIORITY = 100

        class PluginB(PluginBase):
            NAME = "_test_reject"
            PRIORITY = 10

        registry.register(PluginA)
        registry.register(PluginB)
        assert registry.get("_test_reject") is PluginA

    def test_equal_priority_overwrites(self):
        registry = PluginRegistry()

        class PluginA(PluginBase):
            NAME = "_test_equal"
            PRIORITY = 50

        class PluginB(PluginBase):
            NAME = "_test_equal"
            PRIORITY = 50

        registry.register(PluginA)
        registry.register(PluginB)
        assert registry.get("_test_equal") is PluginB


class TestBuiltinsBeforeExtensions:
    def test_fallback_plugins_present_with_lowest_priority(self):
        loader_all = image_loader_resolver.registry.list_all()
        assert loader_all[-1].PRIORITY == -100

    def test_builtins_not_overridden_by_extensions(self):
        assert image_loader_resolver.registry.get("system_thumbnail") is not None
        assert image_loader_resolver.registry.get("system_thumbnail").PRIORITY == -100
