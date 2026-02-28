import py_compile
import pytest
from unittest.mock import MagicMock, patch
from PySide6 import QtCore, QtGui

from source.utils.formatting import dpix


def test_compile():
    py_compile.compile('source/app/viewer/grid/grid_view.py')


def _make_image(w, h):
    return QtGui.QImage(w, h, QtGui.QImage.Format_ARGB32)


LOADER_MARGIN = dpix(3) * 2


class MockItem:
    def __init__(self, w=0, h=0):
        self._pixmap = QtGui.QPixmap(w, h) if (w > 0 and h > 0) else QtGui.QPixmap()
        self.current_path = None

    def pixmap(self):
        return self._pixmap

    def set_image(self, image, current_path=None):
        self._pixmap = QtGui.QPixmap.fromImage(image)
        self.current_path = current_path

    def setGeometry(self, rect):
        pass

    def clear(self):
        self._pixmap = QtGui.QPixmap()
        self.current_path = None

    def show(self):
        pass

    def setToolTip(self, text):
        pass

    def update(self):
        pass


class TestNeedsReload:
    @pytest.fixture(autouse=True)
    def _import(self, qtbot):
        from source.app.viewer.grid.grid_view import GridView
        self._needs_reload = GridView._needs_reload
        self._mock_self = MagicMock()

    def _call(self, item, cell_w, cell_h):
        return self._needs_reload(self._mock_self, item, QtCore.QSizeF(cell_w, cell_h))

    def test_pixmap_at_loader_target_no_reload(self):
        item = MockItem(200 - LOADER_MARGIN, 200 - LOADER_MARGIN)
        assert self._call(item, 200, 200) is False

    def test_pixmap_one_below_threshold_needs_reload(self):
        item = MockItem(200 - LOADER_MARGIN - 1, 200 - LOADER_MARGIN)
        assert self._call(item, 200, 200) is True

    def test_large_pixmap_small_cell_no_reload(self):
        item = MockItem(500, 375)
        assert self._call(item, 200, 200) is False

    def test_small_pixmap_large_cell_needs_reload(self):
        item = MockItem(100, 100)
        assert self._call(item, 600, 600) is True

    def test_null_pixmap_no_reload(self):
        item = MockItem()
        assert self._call(item, 200, 200) is False

    def test_no_pixmap_attr_no_reload(self):
        item = MagicMock(spec=[])
        assert self._call(item, 200, 200) is False

    def test_width_insufficient_needs_reload(self):
        item = MockItem(100, 600)
        assert self._call(item, 600, 600) is True

    def test_height_insufficient_needs_reload(self):
        item = MockItem(600, 100)
        assert self._call(item, 600, 600) is True

    def test_both_dimensions_sufficient_no_reload(self):
        item = MockItem(800, 600)
        assert self._call(item, 600, 600) is False

    def test_margin_boundary_exact_match_no_reload(self):
        item = MockItem(600 - LOADER_MARGIN, 600 - LOADER_MARGIN)
        assert self._call(item, 600, 600) is False


class TestEnsureWidgetVisible:
    @pytest.fixture(autouse=True)
    def _import(self, qtbot):
        from source.app.viewer.grid.grid_view import GridView
        self.GridView = GridView

    def _make_fake(self, paths):
        fake = MagicMock()
        fake.items.paths = paths
        fake.widgets = {}
        fake.active_loaders = {}
        fake._widget_plugin_names = {}
        fake._needs_reload = lambda item, size: self.GridView._needs_reload(fake, item, size)
        return fake

    @patch('source.app.viewer.grid.grid_view.thread_pool')
    @patch('source.app.viewer.grid.grid_view.ImageLoaderRunnable')
    def test_small_cached_triggers_loader(self, MockLoader, mock_thread):
        fake = self._make_fake(['img.jpg'])
        fake.rects = {0: QtCore.QRectF(0, 0, 600, 600)}
        fake.image_cache.get.return_value = _make_image(100, 100)
        fake.pixmap_item_pool.acquire.return_value = MockItem()

        self.GridView._ensure_widget_visible(fake, 0)

        MockLoader.assert_called_once()
        mock_thread.submit.assert_called_once()

    @patch('source.app.viewer.grid.grid_view.thread_pool')
    @patch('source.app.viewer.grid.grid_view.ImageLoaderRunnable')
    def test_sufficient_cached_no_loader(self, MockLoader, mock_thread):
        fake = self._make_fake(['img.jpg'])
        fake.rects = {0: QtCore.QRectF(0, 0, 200, 200)}
        fake.image_cache.get.return_value = _make_image(200, 200)
        fake.pixmap_item_pool.acquire.return_value = MockItem()

        self.GridView._ensure_widget_visible(fake, 0)

        MockLoader.assert_not_called()
        mock_thread.submit.assert_not_called()

    @patch('source.app.viewer.grid.grid_view.thread_pool')
    @patch('source.app.viewer.grid.grid_view.ImageLoaderRunnable')
    def test_no_cache_starts_loader(self, MockLoader, mock_thread):
        fake = self._make_fake(['img.jpg'])
        fake.rects = {0: QtCore.QRectF(0, 0, 200, 200)}
        fake.image_cache.get.return_value = None
        fake.pixmap_item_pool.acquire.return_value = MockItem()

        self.GridView._ensure_widget_visible(fake, 0)

        MockLoader.assert_called_once()
        mock_thread.submit.assert_called_once()

    @patch('source.app.viewer.grid.grid_view.thread_pool')
    @patch('source.app.viewer.grid.grid_view.ImageLoaderRunnable')
    def test_active_thread_prevents_duplicate(self, MockLoader, mock_thread):
        fake = self._make_fake(['img.jpg'])
        fake.rects = {0: QtCore.QRectF(0, 0, 200, 200)}
        fake.image_cache.get.return_value = None
        fake.active_loaders = {0: MagicMock()}
        fake.pixmap_item_pool.acquire.return_value = MockItem()

        self.GridView._ensure_widget_visible(fake, 0)

        MockLoader.assert_not_called()

    @patch('source.app.viewer.grid.grid_view.thread_pool')
    @patch('source.app.viewer.grid.grid_view.ImageLoaderRunnable')
    def test_small_cached_sets_image_before_loader(self, MockLoader, mock_thread):
        fake = self._make_fake(['img.jpg'])
        fake.rects = {0: QtCore.QRectF(0, 0, 600, 600)}
        fake.image_cache.get.return_value = _make_image(100, 100)
        mock_item = MockItem()
        fake.pixmap_item_pool.acquire.return_value = mock_item

        self.GridView._ensure_widget_visible(fake, 0)

        assert mock_item.current_path == 'img.jpg'
        MockLoader.assert_called_once()

    @patch('source.app.viewer.grid.grid_view.thread_pool')
    @patch('source.app.viewer.grid.grid_view.ImageLoaderRunnable')
    def test_existing_widget_not_recreated(self, MockLoader, mock_thread):
        fake = self._make_fake(['img.jpg'])
        rect = QtCore.QRectF(0, 0, 200, 200)
        fake.rects = {0: rect}
        existing = MagicMock()
        existing.geometry.return_value = rect
        fake.widgets = {0: existing}

        self.GridView._ensure_widget_visible(fake, 0)

        fake.pixmap_item_pool.acquire.assert_not_called()
        MockLoader.assert_not_called()


class TestOnImageReady:
    @pytest.fixture(autouse=True)
    def _import(self, qtbot):
        from source.app.viewer.grid.grid_view import GridView
        self.GridView = GridView

    def _make_fake(self, paths, widgets=None, threads=None):
        fake = MagicMock()
        fake.items.paths = paths
        fake.widgets = widgets or {}
        fake.active_loaders = threads or {}
        fake.image_cache = {}
        return fake

    def test_stale_path_rejected(self):
        fake = self._make_fake(
            ['new.jpg'],
            widgets={0: MagicMock()},
            threads={0: MagicMock(path='old.jpg')},
        )
        self.GridView._on_image_ready(fake, 0, _make_image(200, 200))

        fake.widgets[0].set_image.assert_not_called()

    def test_matching_path_updates_widget_and_cache(self):
        widget = MagicMock()
        fake = self._make_fake(
            ['img.jpg'],
            widgets={0: widget},
            threads={0: MagicMock(path='img.jpg')},
        )
        image = _make_image(200, 200)

        self.GridView._on_image_ready(fake, 0, image)

        widget.set_image.assert_called_once_with(image, 'img.jpg')
        assert fake.image_cache['img.jpg'] is image

    def test_out_of_range_index_ignored(self):
        fake = self._make_fake(['img.jpg'])
        self.GridView._on_image_ready(fake, 5, _make_image(200, 200))

    def test_no_runnable_still_updates(self):
        widget = MagicMock()
        fake = self._make_fake(
            ['img.jpg'],
            widgets={0: widget},
        )
        image = _make_image(200, 200)

        self.GridView._on_image_ready(fake, 0, image)

        widget.set_image.assert_called_once_with(image, 'img.jpg')
        assert fake.image_cache['img.jpg'] is image

    def test_widget_removed_during_load(self):
        fake = self._make_fake(
            ['img.jpg'],
            widgets={},
            threads={0: MagicMock(path='img.jpg')},
        )
        self.GridView._on_image_ready(fake, 0, _make_image(200, 200))

        assert 'img.jpg' not in fake.image_cache


class TestCachePathKeyIntegration:
    @pytest.fixture(autouse=True)
    def _import(self, qtbot):
        from source.app.viewer.grid.grid_view import GridView
        self.GridView = GridView

    @patch('source.app.viewer.grid.grid_view.thread_pool')
    @patch('source.app.viewer.grid.grid_view.ImageLoaderRunnable')
    def test_resize_then_scroll_triggers_reload(self, MockLoader, mock_thread):
        fake = MagicMock()
        fake.items.paths = ['a.jpg']
        fake.widgets = {}
        fake.active_loaders = {}
        fake._widget_plugin_names = {}
        fake._needs_reload = lambda item, size: self.GridView._needs_reload(fake, item, size)

        small_rect = QtCore.QRectF(0, 0, 200, 200)
        fake.rects = {0: small_rect}
        fake.image_cache.get.return_value = None
        fake.pixmap_item_pool.acquire.return_value = MockItem()

        self.GridView._ensure_widget_visible(fake, 0)
        assert MockLoader.call_count == 1

        mock_item = fake.widgets[0]
        mock_item.set_image(_make_image(200 - LOADER_MARGIN, 200 - LOADER_MARGIN), 'a.jpg')

        MockLoader.reset_mock()
        mock_thread.reset_mock()

        big_rect = QtCore.QRectF(0, 0, 600, 600)
        fake.rects = {0: big_rect}
        fake.widgets = {}
        fake.active_loaders = {}
        small_cached = _make_image(200 - LOADER_MARGIN, 200 - LOADER_MARGIN)
        fake.image_cache.get.return_value = small_cached
        fake.pixmap_item_pool.acquire.return_value = MockItem()

        self.GridView._ensure_widget_visible(fake, 0)

        MockLoader.assert_called_once()
        assert MockLoader.call_args[0][2] == big_rect.size()
