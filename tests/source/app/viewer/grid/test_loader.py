import py_compile
import pytest
from unittest.mock import MagicMock, patch
from PySide6 import QtCore, QtGui

from source.app.viewer.grid.loader import ImageLoaderRunnable
from source.app.viewer.grid.cachemanager import fullsize_key


def test_compile():
    py_compile.compile('source/app/viewer/grid/loader.py')


def _make_image(w, h):
    return QtGui.QImage(w, h, QtGui.QImage.Format_ARGB32)


def _make_grid_view(cached_images=None):
    grid_view = MagicMock()
    cache = {}
    if cached_images:
        cache.update(cached_images)
    grid_view.image_cache = MagicMock()
    grid_view.image_cache.peek = MagicMock(side_effect=lambda k, d=None: cache.get(k, d))
    grid_view.image_cache.__setitem__ = MagicMock(side_effect=cache.__setitem__)
    grid_view.error_placeholder = _make_image(50, 50)
    return grid_view, cache


class TestCacheHitWithSufficientSize:
    def test_cache_hit_when_cached_larger(self):
        cached_img = _make_image(300, 300)
        grid_view, cache = _make_grid_view({"test.jpg": cached_img})

        runnable = ImageLoaderRunnable(0, "test.jpg", QtCore.QSize(200, 200), grid_view)
        emitted = []
        runnable.signal.image_ready.connect(lambda idx, img: emitted.append((idx, img)))

        with patch("source.app.viewer.grid.loader.grid_resolver") as mock_gh:
            mock_gh.resolve.return_value = None
            runnable.run()

        assert len(emitted) == 1
        assert emitted[0][0] == 0
        assert emitted[0][1] is cached_img
        mock_gh.load.assert_not_called()

    def test_cache_hit_when_cached_exact_size(self):
        cached_img = _make_image(194, 194)
        grid_view, cache = _make_grid_view({"test.jpg": cached_img})

        runnable = ImageLoaderRunnable(0, "test.jpg", QtCore.QSize(200, 200), grid_view)
        emitted = []
        runnable.signal.image_ready.connect(lambda idx, img: emitted.append((idx, img)))

        with patch("source.app.viewer.grid.loader.grid_resolver") as mock_gh:
            mock_gh.resolve.return_value = None
            runnable.run()

        assert len(emitted) == 1
        assert emitted[0][1] is cached_img

    def test_cache_miss_when_cached_smaller(self):
        cached_img = _make_image(100, 100)
        grid_view, cache = _make_grid_view({"test.jpg": cached_img})
        new_img = _make_image(194, 194)

        runnable = ImageLoaderRunnable(0, "test.jpg", QtCore.QSize(200, 200), grid_view)
        emitted = []
        runnable.signal.image_ready.connect(lambda idx, img: emitted.append((idx, img)))

        with patch("source.app.viewer.grid.loader.grid_resolver") as mock_gh:
            mock_gh.resolve.return_value = None
            mock_gh.load.return_value = new_img
            runnable.run()

        mock_gh.load.assert_called_once()
        assert len(emitted) == 1
        assert emitted[0][1] is new_img

    def test_cache_miss_when_no_cache(self):
        grid_view, cache = _make_grid_view()
        new_img = _make_image(194, 194)

        runnable = ImageLoaderRunnable(0, "test.jpg", QtCore.QSize(200, 200), grid_view)
        emitted = []
        runnable.signal.image_ready.connect(lambda idx, img: emitted.append((idx, img)))

        with patch("source.app.viewer.grid.loader.grid_resolver") as mock_gh:
            mock_gh.resolve.return_value = None
            mock_gh.load.return_value = new_img
            runnable.run()

        mock_gh.load.assert_called_once()
        assert len(emitted) == 1

    def test_loader_does_not_write_cache(self):
        grid_view, cache = _make_grid_view()
        new_img = _make_image(194, 194)

        runnable = ImageLoaderRunnable(0, "test.jpg", QtCore.QSize(200, 200), grid_view)
        runnable.signal.image_ready.connect(lambda *_: None)

        with patch("source.app.viewer.grid.loader.grid_resolver") as mock_gh:
            mock_gh.resolve.return_value = None
            mock_gh.load.return_value = new_img
            runnable.run()

        grid_view.image_cache.__setitem__.assert_not_called()

    def test_cancelled_skips_cache_emit(self):
        cached_img = _make_image(300, 300)
        grid_view, cache = _make_grid_view({"test.jpg": cached_img})

        runnable = ImageLoaderRunnable(0, "test.jpg", QtCore.QSize(200, 200), grid_view)
        runnable.cancel()
        emitted = []
        runnable.signal.image_ready.connect(lambda idx, img: emitted.append((idx, img)))

        with patch("source.app.viewer.grid.loader.grid_resolver") as mock_gh:
            mock_gh.resolve.return_value = None
            runnable.run()

        assert len(emitted) == 0

    def test_cache_miss_width_sufficient_height_insufficient(self):
        cached_img = _make_image(300, 100)
        grid_view, cache = _make_grid_view({"test.jpg": cached_img})
        new_img = _make_image(194, 194)

        runnable = ImageLoaderRunnable(0, "test.jpg", QtCore.QSize(200, 200), grid_view)
        emitted = []
        runnable.signal.image_ready.connect(lambda idx, img: emitted.append((idx, img)))

        with patch("source.app.viewer.grid.loader.grid_resolver") as mock_gh:
            mock_gh.resolve.return_value = None
            mock_gh.load.return_value = new_img
            runnable.run()

        mock_gh.load.assert_called_once()
        assert emitted[0][1] is new_img

    def test_viewer_cache_fallback_hit(self):
        fullsize_img = _make_image(2000, 2000)
        grid_view, cache = _make_grid_view({fullsize_key("test.jpg"): fullsize_img})

        runnable = ImageLoaderRunnable(0, "test.jpg", QtCore.QSize(200, 200), grid_view)
        emitted = []
        runnable.signal.image_ready.connect(lambda idx, img: emitted.append((idx, img)))

        with patch("source.app.viewer.grid.loader.grid_resolver") as mock_gh:
            mock_gh.resolve.return_value = None
            runnable.run()

        assert len(emitted) == 1
        assert emitted[0][1] is fullsize_img
        mock_gh.load.assert_not_called()

    def test_fullsize_cache_preferred_over_grid_cache(self):
        grid_img = _make_image(300, 300)
        viewer_img = _make_image(2000, 2000)
        grid_view, cache = _make_grid_view({
            "test.jpg": grid_img,
            fullsize_key("test.jpg"): viewer_img,
        })

        runnable = ImageLoaderRunnable(0, "test.jpg", QtCore.QSize(200, 200), grid_view)
        emitted = []
        runnable.signal.image_ready.connect(lambda idx, img: emitted.append((idx, img)))

        with patch("source.app.viewer.grid.loader.grid_resolver") as mock_gh:
            mock_gh.resolve.return_value = None
            runnable.run()

        assert len(emitted) == 1
        assert emitted[0][1] is viewer_img

    def test_viewer_cache_too_small_triggers_load(self):
        small_img = _make_image(100, 100)
        grid_view, cache = _make_grid_view({fullsize_key("test.jpg"): small_img})
        new_img = _make_image(194, 194)

        runnable = ImageLoaderRunnable(0, "test.jpg", QtCore.QSize(200, 200), grid_view)
        emitted = []
        runnable.signal.image_ready.connect(lambda idx, img: emitted.append((idx, img)))

        with patch("source.app.viewer.grid.loader.grid_resolver") as mock_gh:
            mock_gh.resolve.return_value = None
            mock_gh.load.return_value = new_img
            runnable.run()

        mock_gh.load.assert_called_once()
        assert emitted[0][1] is new_img


class TestRunnablePathCapture:
    def test_runnable_captures_path_at_creation(self):
        grid_view, cache = _make_grid_view()
        runnable = ImageLoaderRunnable(0, "original.jpg", QtCore.QSize(200, 200), grid_view)
        assert runnable.path == "original.jpg"

    def test_runnable_emits_with_captured_index(self):
        grid_view, cache = _make_grid_view()
        new_img = _make_image(194, 194)

        runnable = ImageLoaderRunnable(5, "test.jpg", QtCore.QSize(200, 200), grid_view)
        emitted = []
        runnable.signal.image_ready.connect(lambda idx, img: emitted.append((idx, img)))

        with patch("source.app.viewer.grid.loader.grid_resolver") as mock_gh:
            mock_gh.resolve.return_value = None
            mock_gh.load.return_value = new_img
            runnable.run()

        assert emitted[0][0] == 5

    def test_cancelled_after_load_start_skips_emit(self):
        grid_view, cache = _make_grid_view()
        new_img = _make_image(194, 194)
        emitted = []

        runnable = ImageLoaderRunnable(0, "test.jpg", QtCore.QSize(200, 200), grid_view)
        runnable.signal.image_ready.connect(lambda idx, img: emitted.append((idx, img)))

        def load_and_cancel(path, size):
            runnable.cancel()
            return new_img

        with patch("source.app.viewer.grid.loader.grid_resolver") as mock_gh:
            mock_gh.resolve.return_value = None
            mock_gh.load.side_effect = load_and_cancel
            runnable.run()

        assert len(emitted) == 0
