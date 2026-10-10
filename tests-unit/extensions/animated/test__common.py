import struct
from unittest.mock import MagicMock
from PySide6 import QtCore, QtGui


class TestIsAnimated:
    def test_animated_gif(self, tmp_path):
        from extensions.animated._common import is_animated
        from PIL import Image

        gif_path = str(tmp_path / "anim.gif")
        frames = [Image.new("RGB", (10, 10), c) for c in ["red", "blue"]]
        frames[0].save(gif_path, save_all=True, append_images=frames[1:], duration=100, loop=0)
        assert is_animated(gif_path) is True

    def test_static_gif(self, tmp_path):
        from extensions.animated._common import is_animated
        from PIL import Image

        gif_path = str(tmp_path / "static.gif")
        Image.new("RGB", (10, 10)).save(gif_path)
        assert is_animated(gif_path) is False

    def test_static_png(self, tmp_path):
        from extensions.animated._common import is_animated
        from PIL import Image

        png_path = str(tmp_path / "static.png")
        Image.new("RGB", (10, 10)).save(png_path)
        assert is_animated(png_path) is False

    def test_png_with_actl_in_data_not_chunk(self, tmp_path):
        from extensions.animated._common import is_animated

        png_path = str(tmp_path / "fake_anim.png")
        sig = b"\x89PNG\r\n\x1a\n"
        data_with_actl = b"\x00" * 4 + b"acTL" + b"\x00" * 5
        ihdr = struct.pack(">I", len(data_with_actl)) + b"IHDR" + data_with_actl + b"\x00" * 4
        idat = struct.pack(">I", 0) + b"IDAT" + b"\x00" * 4
        with open(png_path, "wb") as f:
            f.write(sig + ihdr + idat)
        assert is_animated(png_path) is False

    def test_apng_extension(self, tmp_path):
        from extensions.animated._common import is_animated

        apng_path = str(tmp_path / "anim.apng")
        with open(apng_path, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n")
        assert is_animated(apng_path) is True

    def test_png_with_actl_chunk(self, tmp_path):
        from extensions.animated._common import is_animated

        png_path = str(tmp_path / "anim.png")
        sig = b"\x89PNG\r\n\x1a\n"
        ihdr = struct.pack(">I", 13) + b"IHDR" + b"\x00" * 13 + b"\x00" * 4
        actl = struct.pack(">I", 8) + b"acTL" + b"\x00" * 8 + b"\x00" * 4
        with open(png_path, "wb") as f:
            f.write(sig + ihdr + actl)
        assert is_animated(png_path) is True

    def test_animated_webp(self, tmp_path):
        from extensions.animated._common import is_animated

        webp_path = str(tmp_path / "anim.webp")
        riff_header = b"RIFF" + b"\x00" * 4 + b"WEBP"
        vp8x = b"VP8X" + struct.pack("<I", 10) + b"\x00" * 10
        anim = b"ANIM" + struct.pack("<I", 6) + b"\x00" * 6
        with open(webp_path, "wb") as f:
            f.write(riff_header + vp8x + anim)
        assert is_animated(webp_path) is True

    def test_static_webp(self, tmp_path):
        from extensions.animated._common import is_animated
        from PIL import Image

        webp_path = str(tmp_path / "static.webp")
        Image.new("RGB", (10, 10)).save(webp_path, "WEBP")
        assert is_animated(webp_path) is False

    def test_nonexistent_file(self):
        from extensions.animated._common import is_animated

        assert is_animated("/nonexistent/file.gif") is False

    def test_unknown_extension(self, tmp_path):
        from extensions.animated._common import is_animated

        txt_path = str(tmp_path / "file.txt")
        with open(txt_path, "w") as f:
            f.write("hello")
        assert is_animated(txt_path) is False


class TestDecodeFrames:
    def test_decodes_animated_gif(self, qapp, tmp_path):
        from extensions.animated._common import decode_frames
        from PIL import Image

        gif_path = str(tmp_path / "test.gif")
        imgs = [Image.new("RGB", (10, 10), c) for c in ["red", "blue"]]
        imgs[0].save(gif_path, save_all=True, append_images=imgs[1:], duration=100, loop=0)
        pixmaps, delays = decode_frames(gif_path, None, lambda: False)
        assert len(pixmaps) == 2
        assert len(delays) == 2

    def test_cancel_returns_empty(self, qapp, tmp_path):
        from extensions.animated._common import decode_frames
        from PIL import Image

        gif_path = str(tmp_path / "many.gif")
        imgs = [Image.new("RGB", (10, 10), "red") for _ in range(20)]
        imgs[0].save(gif_path, save_all=True, append_images=imgs[1:], duration=50, loop=0)
        pixmaps, delays = decode_frames(gif_path, None, lambda: True)
        assert pixmaps == [] and delays == []

    def test_scaled_size(self, qapp, tmp_path):
        from extensions.animated._common import decode_frames
        from PIL import Image

        gif_path = str(tmp_path / "big.gif")
        imgs = [Image.new("RGB", (100, 100), c) for c in ["red", "blue"]]
        imgs[0].save(gif_path, save_all=True, append_images=imgs[1:], duration=100, loop=0)
        pixmaps, delays = decode_frames(gif_path, QtCore.QSize(50, 50), lambda: False)
        assert len(pixmaps) == 2
        for px in pixmaps:
            assert px.width() <= 50 and px.height() <= 50

    def test_nonexistent_file(self, qapp):
        from extensions.animated._common import decode_frames

        pixmaps, delays = decode_frames("/nonexistent/file.gif", None, lambda: False)
        assert pixmaps == []
        assert delays == []

    def test_decodes_apng(self, qapp, tmp_path):
        from extensions.animated._common import decode_frames
        from PIL import Image

        apng_path = str(tmp_path / "test.apng")
        imgs = [Image.new("RGBA", (10, 10), c) for c in ["red", "blue", "green"]]
        imgs[0].save(apng_path, "PNG", save_all=True, append_images=imgs[1:], duration=[100, 200, 300], loop=0)
        pixmaps, delays = decode_frames(apng_path, None, lambda: False)
        assert len(pixmaps) == 3
        assert delays == [100, 200, 300]

    def test_decodes_apng_with_png_extension(self, qapp, tmp_path):
        from extensions.animated._common import decode_frames
        from PIL import Image

        png_path = str(tmp_path / "anim.png")
        imgs = [Image.new("RGBA", (10, 10), c) for c in ["red", "blue"]]
        imgs[0].save(png_path, "PNG", save_all=True, append_images=imgs[1:], duration=100, loop=0)
        pixmaps, delays = decode_frames(png_path, None, lambda: False)
        assert len(pixmaps) == 2
        assert len(delays) == 2

    def test_apng_cancel_returns_empty(self, qapp, tmp_path):
        from extensions.animated._common import decode_frames
        from PIL import Image

        apng_path = str(tmp_path / "cancel.apng")
        imgs = [Image.new("RGBA", (10, 10), "red") for _ in range(10)]
        imgs[0].save(apng_path, "PNG", save_all=True, append_images=imgs[1:], duration=50, loop=0)
        pixmaps, delays = decode_frames(apng_path, None, lambda: True)
        assert pixmaps == [] and delays == []

    def test_apng_scaled_size(self, qapp, tmp_path):
        from extensions.animated._common import decode_frames
        from PIL import Image

        apng_path = str(tmp_path / "big.apng")
        imgs = [Image.new("RGBA", (100, 100), c) for c in ["red", "blue"]]
        imgs[0].save(apng_path, "PNG", save_all=True, append_images=imgs[1:], duration=100, loop=0)
        pixmaps, delays = decode_frames(apng_path, QtCore.QSize(50, 50), lambda: False)
        assert len(pixmaps) == 2
        for px in pixmaps:
            assert px.width() <= 50 and px.height() <= 50


class TestFrameCache:
    def test_put_and_get(self):
        from extensions.animated._common import FrameCache

        cache = FrameCache()
        frames = [MagicMock()]
        delays = [100]
        cache.put("a.gif", frames, delays)
        result = cache.get("a.gif")
        assert result == (frames, delays)

    def test_get_missing_returns_none(self):
        from extensions.animated._common import FrameCache

        cache = FrameCache()
        assert cache.get("missing.gif") is None

    def test_lru_eviction(self):
        from extensions.animated._common import FrameCache

        cache = FrameCache(max_entries=2)
        cache.put("a.gif", [MagicMock()], [100])
        cache.put("b.gif", [MagicMock()], [100])
        cache.put("c.gif", [MagicMock()], [100])
        assert cache.get("a.gif") is None
        assert cache.get("b.gif") is not None
        assert cache.get("c.gif") is not None

    def test_lru_access_refreshes_order(self):
        from extensions.animated._common import FrameCache

        cache = FrameCache(max_entries=2)
        cache.put("a.gif", [MagicMock()], [100])
        cache.put("b.gif", [MagicMock()], [100])
        cache.get("a.gif")
        cache.put("c.gif", [MagicMock()], [100])
        assert cache.get("a.gif") is not None
        assert cache.get("b.gif") is None

    def test_clear(self):
        from extensions.animated._common import FrameCache

        cache = FrameCache()
        cache.put("a.gif", [MagicMock()], [100])
        cache.clear()
        assert cache.get("a.gif") is None

    def test_remove(self):
        from extensions.animated._common import FrameCache

        cache = FrameCache()
        cache.put("a.gif", [MagicMock()], [100])
        cache.remove("a.gif")
        assert cache.get("a.gif") is None

    def test_remove_missing_key_no_error(self):
        from extensions.animated._common import FrameCache

        cache = FrameCache()
        cache.remove("nonexistent.gif")

    def test_overwrite_existing_entry(self):
        from extensions.animated._common import FrameCache

        cache = FrameCache(max_entries=2)
        frames1 = [MagicMock()]
        frames2 = [MagicMock(), MagicMock()]
        cache.put("a.gif", frames1, [100])
        cache.put("a.gif", frames2, [50, 50])
        result = cache.get("a.gif")
        assert result == (frames2, [50, 50])

    def test_get_if_sufficient_returns_entry_when_large_enough(self):
        from extensions.animated._common import FrameCache

        cache = FrameCache()
        pm = QtGui.QPixmap(200, 100)
        cache.put("a.gif", [pm], [100])
        result = cache.get_if_sufficient("a.gif", QtCore.QSize(200, 100))
        assert result is not None
        assert result[0][0].width() == 200

    def test_get_if_sufficient_evicts_undersized_entry(self):
        from extensions.animated._common import FrameCache

        cache = FrameCache()
        pm = QtGui.QPixmap(50, 50)
        cache.put("a.gif", [pm], [100])
        result = cache.get_if_sufficient("a.gif", QtCore.QSize(200, 200))
        assert result is None
        assert cache.get("a.gif") is None

    def test_get_if_sufficient_returns_none_for_missing(self):
        from extensions.animated._common import FrameCache

        cache = FrameCache()
        assert cache.get_if_sufficient("missing.gif", QtCore.QSize(10, 10)) is None

    def test_thread_safety_put_get(self):
        import threading
        from extensions.animated._common import FrameCache

        cache = FrameCache(max_entries=64)
        errors = []

        def writer(start):
            try:
                for i in range(50):
                    mock_pm = MagicMock()
                    mock_pm.width.return_value = 100
                    mock_pm.height.return_value = 100
                    cache.put(f"{start}_{i}.gif", [mock_pm], [100])
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(100):
                    cache.get("0_0.gif")
                    cache.get_if_sufficient("0_1.gif", QtCore.QSize(10, 10))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(3)]
        threads += [threading.Thread(target=reader) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors


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

    def test_unregister_keeps_timer_with_remaining_cells(self, qtbot):
        from extensions.animated._common import AnimationDriver

        driver = AnimationDriver()
        cell1 = MagicMock()
        cell2 = MagicMock()
        driver.register(cell1)
        driver.register(cell2)
        driver.unregister(cell1)
        assert driver._timer.isActive()
        driver.unregister(cell2)

    def test_register_idempotent(self, qtbot):
        from extensions.animated._common import AnimationDriver

        driver = AnimationDriver()
        cell = MagicMock()
        driver.register(cell)
        driver.register(cell)
        assert len(driver._cells) == 1
        driver.unregister(cell)

    def test_unregister_nonexistent_no_error(self):
        from extensions.animated._common import AnimationDriver

        driver = AnimationDriver()
        driver.unregister(MagicMock())

    def test_tick_calls_advance_on_cells(self, qtbot):
        from extensions.animated._common import AnimationDriver

        driver = AnimationDriver()
        cell = MagicMock()
        driver.register(cell)
        driver._tick()
        cell.advance.assert_called_once()
        driver.unregister(cell)
