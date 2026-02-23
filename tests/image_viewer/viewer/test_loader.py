import py_compile
import pytest
from unittest.mock import MagicMock, patch
from PySide6 import QtCore, QtGui

from source.image_viewer.viewer.loader import ImageLoaderRunnable


def test_compile():
    py_compile.compile('source/image_viewer/viewer/loader.py')


def _make_image(w, h):
    return QtGui.QImage(w, h, QtGui.QImage.Format_ARGB32)


def _make_receiver(cached_images=None):
    receiver = MagicMock()
    cache = {}
    if cached_images:
        cache.update(cached_images)
    receiver.image_cache = MagicMock()
    receiver.image_cache.peek = MagicMock(side_effect=lambda k, d=None: cache.get(k, d))
    receiver.image_cache.__setitem__ = MagicMock(side_effect=cache.__setitem__)
    receiver.error_placeholder = _make_image(50, 50)
    return receiver, cache


class TestCacheHitWithSufficientSize:
    def test_cache_hit_when_cached_larger(self):
        cached_img = _make_image(300, 300)
        receiver, cache = _make_receiver({"test.jpg": cached_img})

        runnable = ImageLoaderRunnable(0, "test.jpg", QtCore.QSize(200, 200), receiver)
        emitted = []
        runnable.signal.image_ready.connect(lambda idx, img: emitted.append((idx, img)))

        with patch("source.image_viewer.viewer.loader.grid_handler") as mock_gh:
            mock_gh.resolve.return_value = None
            runnable.run()

        assert len(emitted) == 1
        assert emitted[0][0] == 0
        assert emitted[0][1] is cached_img
        mock_gh.load.assert_not_called()

    def test_cache_hit_when_cached_exact_size(self):
        cached_img = _make_image(194, 194)
        receiver, cache = _make_receiver({"test.jpg": cached_img})

        runnable = ImageLoaderRunnable(0, "test.jpg", QtCore.QSize(200, 200), receiver)
        emitted = []
        runnable.signal.image_ready.connect(lambda idx, img: emitted.append((idx, img)))

        with patch("source.image_viewer.viewer.loader.grid_handler") as mock_gh:
            mock_gh.resolve.return_value = None
            runnable.run()

        assert len(emitted) == 1
        assert emitted[0][1] is cached_img

    def test_cache_miss_when_cached_smaller(self):
        cached_img = _make_image(100, 100)
        receiver, cache = _make_receiver({"test.jpg": cached_img})
        new_img = _make_image(194, 194)

        runnable = ImageLoaderRunnable(0, "test.jpg", QtCore.QSize(200, 200), receiver)
        emitted = []
        runnable.signal.image_ready.connect(lambda idx, img: emitted.append((idx, img)))

        with patch("source.image_viewer.viewer.loader.grid_handler") as mock_gh:
            mock_gh.resolve.return_value = None
            mock_gh.load.return_value = new_img
            runnable.run()

        mock_gh.load.assert_called_once()
        assert len(emitted) == 1
        assert emitted[0][1] is new_img

    def test_cache_miss_when_no_cache(self):
        receiver, cache = _make_receiver()
        new_img = _make_image(194, 194)

        runnable = ImageLoaderRunnable(0, "test.jpg", QtCore.QSize(200, 200), receiver)
        emitted = []
        runnable.signal.image_ready.connect(lambda idx, img: emitted.append((idx, img)))

        with patch("source.image_viewer.viewer.loader.grid_handler") as mock_gh:
            mock_gh.resolve.return_value = None
            mock_gh.load.return_value = new_img
            runnable.run()

        mock_gh.load.assert_called_once()
        assert len(emitted) == 1

    def test_loader_does_not_write_cache(self):
        receiver, cache = _make_receiver()
        new_img = _make_image(194, 194)

        runnable = ImageLoaderRunnable(0, "test.jpg", QtCore.QSize(200, 200), receiver)
        runnable.signal.image_ready.connect(lambda *_: None)

        with patch("source.image_viewer.viewer.loader.grid_handler") as mock_gh:
            mock_gh.resolve.return_value = None
            mock_gh.load.return_value = new_img
            runnable.run()

        receiver.image_cache.__setitem__.assert_not_called()

    def test_cancelled_skips_cache_emit(self):
        cached_img = _make_image(300, 300)
        receiver, cache = _make_receiver({"test.jpg": cached_img})

        runnable = ImageLoaderRunnable(0, "test.jpg", QtCore.QSize(200, 200), receiver)
        runnable.cancel()
        emitted = []
        runnable.signal.image_ready.connect(lambda idx, img: emitted.append((idx, img)))

        with patch("source.image_viewer.viewer.loader.grid_handler") as mock_gh:
            mock_gh.resolve.return_value = None
            runnable.run()

        assert len(emitted) == 0

    def test_cache_miss_width_sufficient_height_insufficient(self):
        cached_img = _make_image(300, 100)
        receiver, cache = _make_receiver({"test.jpg": cached_img})
        new_img = _make_image(194, 194)

        runnable = ImageLoaderRunnable(0, "test.jpg", QtCore.QSize(200, 200), receiver)
        emitted = []
        runnable.signal.image_ready.connect(lambda idx, img: emitted.append((idx, img)))

        with patch("source.image_viewer.viewer.loader.grid_handler") as mock_gh:
            mock_gh.resolve.return_value = None
            mock_gh.load.return_value = new_img
            runnable.run()

        mock_gh.load.assert_called_once()
        assert emitted[0][1] is new_img


class TestRunnablePathCapture:
    def test_runnable_captures_path_at_creation(self):
        receiver, cache = _make_receiver()
        runnable = ImageLoaderRunnable(0, "original.jpg", QtCore.QSize(200, 200), receiver)
        assert runnable.path == "original.jpg"

    def test_runnable_emits_with_captured_index(self):
        receiver, cache = _make_receiver()
        new_img = _make_image(194, 194)

        runnable = ImageLoaderRunnable(5, "test.jpg", QtCore.QSize(200, 200), receiver)
        emitted = []
        runnable.signal.image_ready.connect(lambda idx, img: emitted.append((idx, img)))

        with patch("source.image_viewer.viewer.loader.grid_handler") as mock_gh:
            mock_gh.resolve.return_value = None
            mock_gh.load.return_value = new_img
            runnable.run()

        assert emitted[0][0] == 5

    def test_cancelled_after_load_start_skips_emit(self):
        receiver, cache = _make_receiver()
        new_img = _make_image(194, 194)
        emitted = []

        runnable = ImageLoaderRunnable(0, "test.jpg", QtCore.QSize(200, 200), receiver)
        runnable.signal.image_ready.connect(lambda idx, img: emitted.append((idx, img)))

        def load_and_cancel(path, size):
            runnable.cancel()
            return new_img

        with patch("source.image_viewer.viewer.loader.grid_handler") as mock_gh:
            mock_gh.resolve.return_value = None
            mock_gh.load.side_effect = load_and_cancel
            runnable.run()

        assert len(emitted) == 0
