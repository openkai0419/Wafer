import os
import sys

import pytest

from wafer.plugin.loader import _import_extension, _discover_plugins, get_plugin_dir, qualify_plugin_name
from wafer.plugin.registry import PluginBase


EXTENSIONS_DIR = get_plugin_dir()
EXTENSION_FOLDERS = sorted(name for name in os.listdir(EXTENSIONS_DIR) if os.path.isdir(os.path.join(EXTENSIONS_DIR, name)) and not name.startswith(".") and name != "__pycache__")


class TestExtensionDiscovery:
    @pytest.mark.parametrize("ext_name", EXTENSION_FOLDERS)
    def test_extension_importable(self, ext_name):
        folder = os.path.join(EXTENSIONS_DIR, ext_name)
        found = _import_extension(ext_name, folder)
        assert isinstance(found, list)

    @pytest.mark.parametrize("ext_name", EXTENSION_FOLDERS)
    def test_discovered_plugins_have_name(self, ext_name):
        folder = os.path.join(EXTENSIONS_DIR, ext_name)
        found = _import_extension(ext_name, folder)
        for registry_key, cls in found:
            assert getattr(cls, "NAME", ""), f"{cls.__name__} in {ext_name} has no NAME"

    @pytest.mark.parametrize("ext_name", EXTENSION_FOLDERS)
    def test_discovered_plugins_have_int_priority(self, ext_name):
        folder = os.path.join(EXTENSIONS_DIR, ext_name)
        found = _import_extension(ext_name, folder)
        for registry_key, cls in found:
            assert isinstance(cls.PRIORITY, int), f"{cls.__name__}.PRIORITY is not int"

    @pytest.mark.parametrize("ext_name", EXTENSION_FOLDERS)
    def test_discovered_plugins_are_pluginbase_subclass(self, ext_name):
        folder = os.path.join(EXTENSIONS_DIR, ext_name)
        found = _import_extension(ext_name, folder)
        for registry_key, cls in found:
            assert issubclass(cls, PluginBase), f"{cls.__name__} is not a PluginBase subclass"

    @pytest.mark.parametrize("ext_name", EXTENSION_FOLDERS)
    def test_discovered_plugins_have_valid_registry_key(self, ext_name):
        valid_keys = {"viewer", "grid", "collector", "parser", "filter", "sort", "layout", "panel", "key_value_panel", "rename_source", "imageloader", "command"}
        folder = os.path.join(EXTENSIONS_DIR, ext_name)
        found = _import_extension(ext_name, folder)
        for registry_key, cls in found:
            assert registry_key in valid_keys, f"{cls.__name__} has invalid registry_key: {registry_key}"

    @pytest.mark.parametrize("ext_name", EXTENSION_FOLDERS)
    def test_qualify_plugin_name_format(self, ext_name):
        folder = os.path.join(EXTENSIONS_DIR, ext_name)
        found = _import_extension(ext_name, folder)
        for registry_key, cls in found:
            qualified = qualify_plugin_name(registry_key, cls)
            assert ":" in qualified
            assert qualified == f"{registry_key}:{cls.__name__}"


EXPECTED_PLUGINS = {
    "image": {
        ("imageloader", "ImageFileLoader"),
    },
    "video": {
        ("grid", "VideoGridPlugin"),
        ("viewer", "VideoViewerPlugin"),
        ("command", "VideoGridCommands"),
        ("command", "VideoViewerCommands"),
    },
    "animated": {
        ("grid", "AnimatedGridPlugin"),
        ("viewer", "AnimatedViewerPlugin"),
        ("command", "AnimatedViewerCommands"),
    },
    "wd14": {
        ("collector", "WD14TaggerCollector"),
    },
    "florence": {
        ("collector", "FlorenceCollector"),
        ("panel", "FlorenceSettingsPanelPlugin"),
    },
    "exiftool": {
        ("collector", "ExifToolCollectorPlugin"),
        ("key_value_panel", "ExifToolMetaPanelPlugin"),
        ("panel", "ExifSettingsPanelPlugin"),
    },
    "ffmpeg": {
        ("collector", "FfmpegCollectorPlugin"),
    },
    "text_generation": {
        ("parser", "ComfyUiParser"),
        ("parser", "NovelAiImageParser"),
    },
    "additional_filters": {
        ("filter", "DateRangeFilter"),
        ("filter", "RegexFilter"),
    },
    "additional_layout": {
        ("layout", "MultiSpanLayout"),
        ("layout", "MultiSpanTilingLayout"),
        ("layout", "OptimizedJustifiedLayout"),
        ("layout", "OrganicPartitionLayout"),
    },
    "color": {
        ("collector", "ColorCollector"),
        ("filter", "ColorFilter"),
        ("key_value_panel", "ColorTagPanelPlugin"),
    },
    "zip": {
        ("collector", "ZipCollectorPlugin"),
        ("viewer", "ZipViewerPlugin"),
        ("grid", "ZipGridPlugin"),
        ("imageloader", "ZipImageLoader"),
    },
}


class TestExpectedPluginDiscovery:
    @pytest.mark.parametrize("ext_name", list(EXPECTED_PLUGINS.keys()))
    def test_all_expected_plugins_discovered(self, ext_name):
        folder = os.path.join(EXTENSIONS_DIR, ext_name)
        found = {(rk, cls.__name__) for rk, cls in _import_extension(ext_name, folder)}
        expected = EXPECTED_PLUGINS[ext_name]
        missing = expected - found
        assert not missing, f"Missing plugins in {ext_name}: {missing}"

    def test_no_unexpected_extension_folders(self):
        known = set(EXPECTED_PLUGINS.keys())
        for ext_name in EXTENSION_FOLDERS:
            assert ext_name in known, f"Unknown extension folder: {ext_name}"


class TestExtensionAttributes:
    def test_image_loader_priority(self):
        folder = os.path.join(EXTENSIONS_DIR, "image")
        found = {cls.__name__: cls for _, cls in _import_extension("image", folder)}
        assert found["ImageFileLoader"].PRIORITY == 100

    def test_animated_higher_priority_than_image(self):
        image_folder = os.path.join(EXTENSIONS_DIR, "image")
        animated_folder = os.path.join(EXTENSIONS_DIR, "animated")
        image_found = {cls.__name__: cls for _, cls in _import_extension("image", image_folder)}
        animated_found = {cls.__name__: cls for _, cls in _import_extension("animated", animated_folder)}
        assert animated_found["AnimatedGridPlugin"].PRIORITY > image_found["ImageFileLoader"].PRIORITY

    def test_image_extensions_tuple(self):
        folder = os.path.join(EXTENSIONS_DIR, "image")
        found = {cls.__name__: cls for _, cls in _import_extension("image", folder)}
        exts = found["ImageFileLoader"].EXTENSIONS
        assert ".jpg" in exts
        assert ".jpeg" in exts
        assert ".png" in exts

    def test_video_extensions_tuple(self):
        folder = os.path.join(EXTENSIONS_DIR, "video")
        found = {cls.__name__: cls for _, cls in _import_extension("video", folder)}
        exts = found["VideoGridPlugin"].EXTENSIONS
        assert ".mp4" in exts
        assert ".mkv" in exts
        assert ".webm" in exts

    def test_animated_extensions_overlap_with_image(self):
        image_folder = os.path.join(EXTENSIONS_DIR, "image")
        animated_folder = os.path.join(EXTENSIONS_DIR, "animated")
        image_cls = {cls.__name__: cls for _, cls in _import_extension("image", image_folder)}
        animated_cls = {cls.__name__: cls for _, cls in _import_extension("animated", animated_folder)}
        overlap = set(image_cls["ImageFileLoader"].EXTENSIONS) & set(animated_cls["AnimatedGridPlugin"].EXTENSIONS)
        assert ".gif" in overlap
        assert ".webp" in overlap

    def test_default_enabled_true_for_core_extensions(self):
        for ext_name in ("image", "video", "animated"):
            folder = os.path.join(EXTENSIONS_DIR, ext_name)
            found = _import_extension(ext_name, folder)
            for registry_key, cls in found:
                assert cls.DEFAULT_ENABLED is True, f"{cls.__name__} in {ext_name} should be DEFAULT_ENABLED=True"

    def test_wd14_default_disabled(self):
        from wafer.plugin import BasePanelPlugin

        folder = os.path.join(EXTENSIONS_DIR, "wd14")
        found = _import_extension("wd14", folder)
        for _, cls in found:
            if issubclass(cls, BasePanelPlugin):
                continue
            assert not getattr(cls, "DEFAULT_ENABLED", False), f"{cls.__name__} should be disabled by default"

    def test_text_generation_default_disabled(self):
        folder = os.path.join(EXTENSIONS_DIR, "text_generation")
        found = _import_extension("text_generation", folder)
        for _, cls in found:
            assert not getattr(cls, "DEFAULT_ENABLED", False), f"{cls.__name__} should be disabled by default"
