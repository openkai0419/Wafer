import numpy as np
import pytest
from PySide6 import QtCore, QtGui
from PIL import Image

from wafer.builtins.imageloader import SystemImageLoader
from wafer.builtins.viewer import DefaultViewerPlugin
from wafer.builtins.filters import TextFilter, DirectoryFilter
from wafer.builtins.sorts import (
    NaturalPathSort,
    NaturalNameSort,
    ModifiedSort,
    CreatedSort,
    SizeSort,
    CollectedSort,
    RandomSort,
)
from wafer.plugin.grid.handler import grid_resolver
from wafer.plugin.viewer.handler import viewer_resolver
from wafer.plugin.query.handler import filter_registry, sort_registry
from wafer.plugin.imageloader.base import BaseImageLoader
from wafer.plugin.imageloader.handler import image_loader_resolver
from wafer.plugin.viewer.base import ImageViewerPlugin
from wafer.plugin.query.base import BaseFilterPlugin, BaseSortPlugin


class TestSystemImageLoader:
    def test_is_base_image_loader(self):
        assert issubclass(SystemImageLoader, BaseImageLoader)

    def test_catch_all_extensions(self):
        assert SystemImageLoader.EXTENSIONS == ()

    def test_negative_priority(self):
        assert SystemImageLoader.PRIORITY == -100

    def test_registered_in_imageloader_registry(self):
        assert image_loader_resolver.registry.instance("system_thumbnail") is not None

    def test_load_pil_nonexistent_returns_none(self):
        plugin = SystemImageLoader()
        result = plugin.load_pil("/nonexistent/path.xyz")
        assert result is None

    def test_load_pil_real_image(self, tmp_path):
        img_path = tmp_path / "test.png"
        Image.new("RGB", (100, 100)).save(str(img_path))
        plugin = SystemImageLoader()
        result = plugin.load_pil(str(img_path))
        if result is not None:
            assert isinstance(result, Image.Image)

    def test_load_pil_with_size(self, tmp_path):
        img_path = tmp_path / "test.png"
        Image.new("RGB", (200, 200)).save(str(img_path))
        plugin = SystemImageLoader()
        result = plugin.load_pil(str(img_path), size=64)
        if result is not None:
            assert isinstance(result, Image.Image)

    def test_chain_includes_system_thumbnail_for_jpg(self):
        chain = image_loader_resolver.resolve_chain("photo.jpg")
        assert SystemImageLoader in chain

    def test_chain_system_thumbnail_is_last_for_jpg(self):
        chain = image_loader_resolver.resolve_chain("photo.jpg")
        assert chain[-1] is SystemImageLoader


class TestDefaultViewerPlugin:
    def test_is_image_viewer_plugin(self):
        assert issubclass(DefaultViewerPlugin, ImageViewerPlugin)

    def test_catch_all_extensions(self):
        assert DefaultViewerPlugin.EXTENSIONS == ()

    def test_negative_priority(self):
        assert DefaultViewerPlugin.PRIORITY == -100

    def test_registered_in_viewer_registry(self):
        assert viewer_resolver.registry.instance("default_viewer") is not None

    def test_load_content_real_image(self, tmp_path):
        img_path = tmp_path / "test.jpg"
        Image.new("RGB", (50, 50)).save(str(img_path))
        plugin = DefaultViewerPlugin()
        result = plugin.load_content(str(img_path))
        assert result is not None
        assert isinstance(result, QtGui.QImage)

    def test_load_content_nonexistent(self):
        plugin = DefaultViewerPlugin()
        result = plugin.load_content("/nonexistent/file.xyz")
        assert result is None


class TestBuiltinFilters:
    def test_text_filter_registered(self):
        assert filter_registry.get("text") is TextFilter

    def test_directory_filter_registered(self):
        assert filter_registry.get("directory") is DirectoryFilter

    def test_text_filter_is_base_filter_plugin(self):
        assert issubclass(TextFilter, BaseFilterPlugin)

    def test_directory_filter_is_base_filter_plugin(self):
        assert issubclass(DirectoryFilter, BaseFilterPlugin)


class TestBuiltinSorts:
    def test_all_sorts_registered(self):
        names = {s.NAME for s in sort_registry.list_all()}
        expected = {"path", "name", "modified", "created", "size", "collected", "random"}
        assert expected.issubset(names)

    def test_all_sorts_are_base_sort_plugin(self):
        for cls in [NaturalPathSort, NaturalNameSort, ModifiedSort, CreatedSort, SizeSort, CollectedSort, RandomSort]:
            assert issubclass(cls, BaseSortPlugin)

    def test_natural_path_sort(self):
        rows = [{"path": "img10.png"}, {"path": "img2.png"}, {"path": "img1.png"}]
        result = NaturalPathSort.sort_rows(rows, ascending=True)
        assert [r["path"] for r in result] == ["img1.png", "img2.png", "img10.png"]

    def test_random_sort_returns_all(self):
        rows = [{"path": f"{i}.png"} for i in range(20)]
        result = RandomSort.sort_rows(list(rows), ascending=True)
        assert len(result) == 20


class TestRegisterAll:
    def test_builtins_loaded_via_load_plugins(self):
        assert image_loader_resolver.registry.instance("system_thumbnail") is not None
        assert viewer_resolver.registry.instance("default_viewer") is not None
        assert filter_registry.get("text") is not None
        assert sort_registry.get("path") is not None
