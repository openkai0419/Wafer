import os
import struct
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PIL import Image
from PySide6 import QtCore, QtGui

from wafer.utils.paths import normalize_path
from wafer.plugin.registry import PluginRegistry, BasePlugin
from wafer.plugin.grid.handler import grid_resolver
from wafer.plugin.grid.base import ImageGridPlugin, WidgetGridPlugin, BaseGridPlugin
from wafer.plugin.collector.handler import collector_resolver
from wafer.plugin.viewer.handler import ViewerResolver
from wafer.core.db.indexer import FileIndexer


def _create_test_image(path, width=100, height=80, fmt='JPEG'):
    img = Image.new('RGB', (width, height), color=(255, 0, 0))
    img.save(str(path), format=fmt)


def _create_png(path, w=100, h=80):
    Image.new('RGB', (w, h), color=(0, 128, 255)).save(str(path), format='PNG')


def _create_bmp(path, w=100, h=80):
    Image.new('RGB', (w, h), color=(0, 255, 0)).save(str(path), format='BMP')


def _create_webp(path, w=100, h=80):
    Image.new('RGB', (w, h), color=(255, 255, 0)).save(str(path), format='WEBP')


def _create_animated_gif(path, w=80, h=60, frames=3):
    imgs = [Image.new('RGB', (w, h), color=((i * 80) % 256, 100, 50)) for i in range(frames)]
    imgs[0].save(str(path), save_all=True, append_images=imgs[1:], loop=0, duration=100)


def _create_dummy_file(path, content=b'dummy content'):
    Path(path).write_bytes(content)


class TestGridPluginResolution:

    def test_jpg_resolves_to_image_plugin(self, tmp_path):
        path = str(tmp_path / 'test.jpg')
        _create_test_image(path)
        plugin_cls = grid_resolver.resolve(path)
        assert plugin_cls is not None
        assert issubclass(plugin_cls, ImageGridPlugin)

    def test_jpeg_resolves_to_image_plugin(self, tmp_path):
        path = str(tmp_path / 'test.jpeg')
        _create_test_image(path)
        plugin_cls = grid_resolver.resolve(path)
        assert plugin_cls is not None
        assert issubclass(plugin_cls, ImageGridPlugin)

    def test_png_resolves_to_plugin(self, tmp_path):
        path = str(tmp_path / 'test.png')
        _create_png(path)
        plugin_cls = grid_resolver.resolve(path)
        assert plugin_cls is not None

    def test_bmp_resolves_to_image_plugin(self, tmp_path):
        path = str(tmp_path / 'test.bmp')
        _create_bmp(path)
        plugin_cls = grid_resolver.resolve(path)
        assert plugin_cls is not None
        assert issubclass(plugin_cls, ImageGridPlugin)

    def test_webp_resolves_to_plugin(self, tmp_path):
        path = str(tmp_path / 'test.webp')
        _create_webp(path)
        plugin_cls = grid_resolver.resolve(path)
        assert plugin_cls is not None

    def test_gif_resolves_to_plugin(self, tmp_path):
        path = str(tmp_path / 'anim.gif')
        _create_animated_gif(path)
        plugin_cls = grid_resolver.resolve(path)
        assert plugin_cls is not None

    def test_animated_plugin_priority_over_image_for_gif(self):
        chain = grid_resolver.resolve_chain('test.gif')
        if len(chain) >= 2:
            assert chain[0].PRIORITY >= chain[1].PRIORITY

    def test_video_extensions_resolve(self):
        for ext in ['.mp4', '.mkv', '.webm', '.avi', '.mov']:
            plugin_cls = grid_resolver.resolve(f'test{ext}')
            assert plugin_cls is not None, f'No plugin resolved for {ext}'

    def test_unknown_extension_returns_none(self):
        assert grid_resolver.resolve('test.xyz123') is None
        assert grid_resolver.resolve('test.abc') is None


class TestCollectorPluginResolution:

    def test_exif_collector_registered(self):
        names = collector_resolver.names()
        assert 'exif' in names

    def test_jpg_triggers_exif_collector(self):
        collectors = collector_resolver.collectors_for_path('photo.jpg')
        assert 'exif' in collectors

    def test_png_triggers_exif_collector(self):
        collectors = collector_resolver.collectors_for_path('icon.png')
        assert 'exif' in collectors

    def test_txt_no_exif_collector(self):
        collectors = collector_resolver.collectors_for_path('readme.txt')
        assert 'exif' not in collectors

    def test_unknown_no_collector(self):
        collectors = collector_resolver.collectors_for_path('data.xyz123')
        assert len(collectors) == 0 or 'exif' not in collectors


class TestCollectorProcessExecution:

    def test_collector_processes_real_jpg(self, tmp_path):
        path = tmp_path / 'real.jpg'
        _create_test_image(path, 200, 100)
        norm = normalize_path(str(path))
        plugin = collector_resolver.registry.get('exif')()
        result = plugin.process(norm, (os.stat(str(path)).st_mtime, os.path.getsize(str(path)), 0.0))
        assert result.status is True
        assert result.source == norm
        assert result.aspect == 2.0

    def test_collector_processes_real_png(self, tmp_path):
        path = tmp_path / 'real.png'
        _create_png(path, 64, 64)
        norm = normalize_path(str(path))
        plugin = collector_resolver.registry.get('exif')()
        result = plugin.process(norm, (os.stat(str(path)).st_mtime, os.path.getsize(str(path)), 0.0))
        assert result.status is True
        assert result.aspect == 1.0

    def test_collector_processes_bmp(self, tmp_path):
        path = tmp_path / 'real.bmp'
        _create_bmp(path, 300, 100)
        norm = normalize_path(str(path))
        plugin = collector_resolver.registry.get('exif')()
        result = plugin.process(norm, (os.stat(str(path)).st_mtime, os.path.getsize(str(path)), 0.0))
        assert result.status is True
        assert result.aspect == 3.0

    def test_collector_processes_webp(self, tmp_path):
        path = tmp_path / 'real.webp'
        _create_webp(path, 200, 200)
        norm = normalize_path(str(path))
        plugin = collector_resolver.registry.get('exif')()
        result = plugin.process(norm, (os.stat(str(path)).st_mtime, os.path.getsize(str(path)), 0.0))
        assert result.status is True
        assert result.aspect == 1.0


class TestGridPluginImageLoad:

    def test_image_plugin_loads_jpg(self, tmp_path):
        path = str(tmp_path / 'load.jpg')
        _create_test_image(path, 200, 100)
        instance = grid_resolver.resolve_image_instance(path)
        assert instance is not None
        image = instance.load(path)
        assert image is not None
        assert not image.isNull()

    def test_image_plugin_loads_png(self, tmp_path):
        path = str(tmp_path / 'load.png')
        _create_png(path, 150, 150)
        instance = grid_resolver.resolve_image_instance(path)
        assert instance is not None
        image = instance.load(path)
        assert image is not None
        assert not image.isNull()

    def test_image_plugin_loads_bmp(self, tmp_path):
        path = str(tmp_path / 'load.bmp')
        _create_bmp(path, 80, 80)
        instance = grid_resolver.resolve_image_instance(path)
        assert instance is not None
        image = instance.load(path)
        assert image is not None
        assert not image.isNull()

    def test_image_plugin_loads_webp(self, tmp_path):
        path = str(tmp_path / 'load.webp')
        _create_webp(path, 120, 60)
        instance = grid_resolver.resolve_image_instance(path)
        assert instance is not None
        image = instance.load(path)
        assert image is not None
        assert not image.isNull()

    def test_image_plugin_loads_with_size_constraint(self, tmp_path):
        path = str(tmp_path / 'sized.jpg')
        _create_test_image(path, 800, 600)
        instance = grid_resolver.resolve_image_instance(path)
        size = QtCore.QSize(200, 150)
        image = instance.load(path, size)
        assert image is not None
        assert image.width() == 200
        assert image.height() == 150


class TestFallbackForUnsupportedExtensions:

    def test_fallback_load_for_txt(self, tmp_path):
        path = str(tmp_path / 'readme.txt')
        _create_dummy_file(path, b'hello world')
        result = grid_resolver.load(path)
        # fallback may return None or an image depending on OS thumbnail support

    def test_fallback_load_for_zip(self, tmp_path):
        path = str(tmp_path / 'archive.zip')
        _create_dummy_file(path, b'PK\x03\x04' + b'\x00' * 100)
        result = grid_resolver.load(path)

    def test_fallback_load_for_mp3(self, tmp_path):
        path = str(tmp_path / 'music.mp3')
        _create_dummy_file(path, b'\xff\xfb\x90\x00' + b'\x00' * 100)
        result = grid_resolver.load(path)

    def test_fallback_load_for_mp4(self, tmp_path):
        path = str(tmp_path / 'video.mp4')
        _create_dummy_file(path, b'\x00\x00\x00\x20ftypisom' + b'\x00' * 100)
        result = grid_resolver.load(path)

    def test_fallback_load_for_pdf(self, tmp_path):
        path = str(tmp_path / 'document.pdf')
        _create_dummy_file(path, b'%PDF-1.4' + b'\x00' * 100)
        result = grid_resolver.load(path)

    def test_fallback_load_for_doc(self, tmp_path):
        path = str(tmp_path / 'document.docx')
        _create_dummy_file(path, b'PK\x03\x04' + b'\x00' * 100)
        result = grid_resolver.load(path)

    def test_fallback_load_for_unknown_binary(self, tmp_path):
        path = str(tmp_path / 'data.xyz')
        _create_dummy_file(path, b'\x00\xff' * 50)
        result = grid_resolver.load(path)

    def test_fallback_does_not_crash_for_empty_file(self, tmp_path):
        path = str(tmp_path / 'empty.dat')
        _create_dummy_file(path, b'')
        result = grid_resolver.load(path)

    def test_no_plugin_resolved_for_unsupported(self):
        assert grid_resolver.resolve('file.xyz123') is None
        assert grid_resolver.resolve('file.abc') is None
        assert grid_resolver.resolve('file.dat') is None

    def test_fallback_load_returns_image_for_known_image(self, tmp_path):
        path = str(tmp_path / 'test.jpg')
        _create_test_image(path, 200, 100)
        result = grid_resolver.load(path)
        assert result is not None
        assert isinstance(result, QtGui.QImage)
        assert not result.isNull()


class TestPluginAbsenceDoesntCrash:

    def test_resolve_none_for_missing_extension(self):
        assert grid_resolver.resolve('test.nosuchext') is None

    def test_resolve_chain_empty_for_missing(self):
        chain = grid_resolver.resolve_chain('test.nosuchext')
        assert chain == []

    def test_resolve_instance_none_for_missing(self):
        assert grid_resolver.resolve_instance('test.nosuchext') is None

    def test_load_fallback_for_missing_extension(self, tmp_path):
        path = str(tmp_path / 'test.nosuchext')
        _create_dummy_file(path, b'content')
        result = grid_resolver.load(path)


class TestIndexingWithVariousFileTypes:

    def test_index_mixed_file_types(self, tmp_path):
        mixed_dir = tmp_path / 'mixed'
        mixed_dir.mkdir()
        _create_test_image(mixed_dir / 'photo.jpg', 200, 100)
        _create_png(mixed_dir / 'icon.png', 64, 64)
        _create_bmp(mixed_dir / 'bitmap.bmp', 100, 100)
        _create_webp(mixed_dir / 'web.webp', 120, 80)
        _create_animated_gif(mixed_dir / 'anim.gif')
        _create_dummy_file(mixed_dir / 'readme.txt', b'hello')
        _create_dummy_file(mixed_dir / 'data.bin', b'\x00' * 256)
        _create_dummy_file(mixed_dir / 'archive.zip', b'PK\x03\x04' + b'\x00' * 50)
        _create_dummy_file(mixed_dir / 'song.mp3', b'\xff\xfb\x90\x00' + b'\x00' * 50)
        _create_dummy_file(mixed_dir / 'video.mp4', b'\x00\x00\x00\x20ftypisom' + b'\x00' * 50)

        collectors = collector_resolver.summary()
        db_path = tmp_path / 'test.db'

        with FileIndexer(db_path, collectors=collectors) as idx:
            idx.initialize()
            idx.update_index(str(mixed_dir))

            all_files = idx.db.read_conn.execute("SELECT path FROM files").fetchall()
            assert len(all_files) == 10

            all_sources = idx.db.read_conn.execute("SELECT source, status FROM sources").fetchall()
            assert len(all_sources) == 10

            pending = idx.db.get_pending_sources('exif')
            pending_paths = {row[0] for row in pending}
            for img_name in ['photo.jpg', 'icon.png', 'bitmap.bmp', 'web.webp', 'anim.gif']:
                norm = normalize_path(str(mixed_dir / img_name))
                assert norm in pending_paths, f'{img_name} should have pending exif'

            for non_img in ['readme.txt', 'data.bin', 'archive.zip', 'song.mp3', 'video.mp4']:
                norm = normalize_path(str(mixed_dir / non_img))
                assert norm not in pending_paths, f'{non_img} should not have pending exif'


class TestPluginRegistryDynamics:

    def test_register_and_resolve(self):
        registry = PluginRegistry()

        class TestPlugin(BasePlugin):
            NAME = '_test_dynamic'
            EXTENSIONS = ('.testfmt',)
            PRIORITY = 50

        registry.register(TestPlugin)
        assert registry.resolve('file.testfmt') == TestPlugin
        assert registry.resolve('file.other') is None

    def test_priority_ordering(self):
        registry = PluginRegistry()

        class LowPriority(BasePlugin):
            NAME = '_low'
            EXTENSIONS = ('.shared',)
            PRIORITY = 10

        class HighPriority(BasePlugin):
            NAME = '_high'
            EXTENSIONS = ('.shared',)
            PRIORITY = 100

        registry.register(LowPriority)
        registry.register(HighPriority)
        resolved = registry.resolve('file.shared')
        assert resolved == HighPriority

    def test_name_overwrite(self):
        registry = PluginRegistry()

        class PluginV1(BasePlugin):
            NAME = '_versioned'
            EXTENSIONS = ('.ver',)
            PRIORITY = 10

        class PluginV2(BasePlugin):
            NAME = '_versioned'
            EXTENSIONS = ('.ver',)
            PRIORITY = 20

        registry.register(PluginV1)
        registry.register(PluginV2)
        assert len([p for p in registry.list_all() if p.NAME == '_versioned']) == 1
        assert registry.resolve('file.ver') == PluginV2

    def test_catch_all_plugin(self):
        registry = PluginRegistry()

        class CatchAll(BasePlugin):
            NAME = '_catchall'
            EXTENSIONS = ()
            PRIORITY = 1

        registry.register(CatchAll)
        assert registry.resolve('anything.xyz') == CatchAll
        assert registry.resolve('file.abc') == CatchAll
