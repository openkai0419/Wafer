import os
import struct
import pytest
from unittest.mock import MagicMock
from PySide6 import QtCore, QtGui


class TestIsAnimated:

    def test_animated_gif(self, tmp_path):
        from extensions.animated._common import is_animated
        from PIL import Image
        gif_path = str(tmp_path / 'anim.gif')
        frames = [Image.new('RGB', (10, 10), c) for c in ['red', 'blue']]
        frames[0].save(gif_path, save_all=True, append_images=frames[1:], duration=100, loop=0)
        assert is_animated(gif_path) is True

    def test_static_gif(self, tmp_path):
        from extensions.animated._common import is_animated
        from PIL import Image
        gif_path = str(tmp_path / 'static.gif')
        Image.new('RGB', (10, 10)).save(gif_path)
        assert is_animated(gif_path) is False

    def test_apng_extension(self, tmp_path):
        from extensions.animated._common import is_animated
        apng_path = str(tmp_path / 'anim.apng')
        with open(apng_path, 'wb') as f:
            f.write(b'\x89PNG\r\n\x1a\n')
        assert is_animated(apng_path) is True

    def test_png_with_actl_chunk(self, tmp_path):
        from extensions.animated._common import is_animated
        png_path = str(tmp_path / 'anim.png')
        sig = b'\x89PNG\r\n\x1a\n'
        ihdr = struct.pack('>I', 13) + b'IHDR' + b'\x00' * 13 + b'\x00' * 4
        actl = struct.pack('>I', 8) + b'acTL' + b'\x00' * 8 + b'\x00' * 4
        with open(png_path, 'wb') as f:
            f.write(sig + ihdr + actl)
        assert is_animated(png_path) is True

    def test_animated_webp(self, tmp_path):
        from extensions.animated._common import is_animated
        webp_path = str(tmp_path / 'anim.webp')
        riff_header = b'RIFF' + b'\x00' * 4 + b'WEBP'
        vp8x = b'VP8X' + struct.pack('<I', 10) + b'\x00' * 10
        anim = b'ANIM' + struct.pack('<I', 6) + b'\x00' * 6
        with open(webp_path, 'wb') as f:
            f.write(riff_header + vp8x + anim)
        assert is_animated(webp_path) is True

    def test_static_webp(self, tmp_path):
        from extensions.animated._common import is_animated
        from PIL import Image
        webp_path = str(tmp_path / 'static.webp')
        Image.new('RGB', (10, 10)).save(webp_path, 'WEBP')
        assert is_animated(webp_path) is False

    def test_nonexistent_file(self):
        from extensions.animated._common import is_animated
        assert is_animated('/nonexistent/file.gif') is False

    def test_unknown_extension(self, tmp_path):
        from extensions.animated._common import is_animated
        txt_path = str(tmp_path / 'file.txt')
        with open(txt_path, 'w') as f:
            f.write('hello')
        assert is_animated(txt_path) is False


class TestDecodeFrames:

    def test_decodes_animated_gif(self, qapp, tmp_path):
        from extensions.animated._common import decode_frames
        from PIL import Image
        gif_path = str(tmp_path / 'test.gif')
        imgs = [Image.new('RGB', (10, 10), c) for c in ['red', 'blue']]
        imgs[0].save(gif_path, save_all=True, append_images=imgs[1:], duration=100, loop=0)
        pixmaps, delays = decode_frames(gif_path, None, lambda: False)
        assert len(pixmaps) == 2
        assert len(delays) == 2

    def test_cancel_returns_empty(self, qapp, tmp_path):
        from extensions.animated._common import decode_frames
        from PIL import Image
        gif_path = str(tmp_path / 'many.gif')
        imgs = [Image.new('RGB', (10, 10), 'red') for _ in range(20)]
        imgs[0].save(gif_path, save_all=True, append_images=imgs[1:], duration=50, loop=0)
        pixmaps, delays = decode_frames(gif_path, None, lambda: True)
        assert pixmaps == [] and delays == []

    def test_scaled_size(self, qapp, tmp_path):
        from extensions.animated._common import decode_frames
        from PIL import Image
        gif_path = str(tmp_path / 'big.gif')
        imgs = [Image.new('RGB', (100, 100), c) for c in ['red', 'blue']]
        imgs[0].save(gif_path, save_all=True, append_images=imgs[1:], duration=100, loop=0)
        pixmaps, delays = decode_frames(gif_path, QtCore.QSize(50, 50), lambda: False)
        assert len(pixmaps) == 2
        for px in pixmaps:
            assert px.width() <= 50 and px.height() <= 50

    def test_nonexistent_file(self, qapp):
        from extensions.animated._common import decode_frames
        pixmaps, delays = decode_frames('/nonexistent/file.gif', None, lambda: False)
        assert pixmaps == []
        assert delays == []


class TestFrameCache:

    def test_put_and_get(self):
        from extensions.animated._common import FrameCache
        cache = FrameCache()
        frames = [MagicMock()]
        delays = [100]
        cache.put('a.gif', frames, delays)
        result = cache.get('a.gif')
        assert result == (frames, delays)

    def test_lru_eviction(self):
        from extensions.animated._common import FrameCache
        cache = FrameCache(max_entries=2)
        cache.put('a.gif', [MagicMock()], [100])
        cache.put('b.gif', [MagicMock()], [100])
        cache.put('c.gif', [MagicMock()], [100])
        assert cache.get('a.gif') is None
        assert cache.get('b.gif') is not None


class TestAnimationDriver:

    def test_register_starts_timer(self, qtbot):
        from extensions.animated._common import AnimationDriver
        driver = AnimationDriver()
        cell = MagicMock()
        driver.register(cell)
        assert driver._timer.isActive()
        driver.unregister(cell)

    def test_unregister_stops_timer_when_empty(self, qtbot):
        from extensions.animated._common import AnimationDriver
        driver = AnimationDriver()
        cell = MagicMock()
        driver.register(cell)
        driver.unregister(cell)
        assert not driver._timer.isActive()

    def test_tick_calls_advance(self, qtbot):
        from extensions.animated._common import AnimationDriver
        driver = AnimationDriver()
        cell = MagicMock()
        driver.register(cell)
        driver._tick()
        cell.advance.assert_called_once()
        driver.unregister(cell)


class TestCacheInstances:

    def test_grid_and_viewer_caches_are_separate(self):
        from extensions.animated._common import _grid_cache, _viewer_cache
        assert _grid_cache is not _viewer_cache

    def test_grid_cache_larger_than_viewer(self):
        from extensions.animated._common import _grid_cache, _viewer_cache
        assert _grid_cache._max > _viewer_cache._max
