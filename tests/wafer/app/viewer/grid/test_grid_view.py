import py_compile
import pytest
from unittest.mock import MagicMock, patch
from PySide6 import QtCore, QtGui, QtWidgets

from wafer.utils.formatting import dpix


@pytest.fixture(autouse=True, scope="module")
def _configure_command_store(tmp_path_factory):
    from wafer.core.actions.command.state import CommandOptionStore
    prev = CommandOptionStore._instance, CommandOptionStore._initialized, CommandOptionStore._default_path
    CommandOptionStore._instance = None
    CommandOptionStore._initialized = False
    CommandOptionStore._default_path = None
    CommandOptionStore.configure(tmp_path_factory.mktemp("grid") / "cmd.json")
    yield
    CommandOptionStore._instance, CommandOptionStore._initialized, CommandOptionStore._default_path = prev


def test_compile():
    py_compile.compile('wafer/app/viewer/grid/grid_view.py')


class TestSelectionOverlay:
    @pytest.fixture(autouse=True)
    def _import(self, qtbot):
        from wafer.app.viewer.grid.grid_view import _SelectionOverlay
        self._cls = _SelectionOverlay

    def test_attributes_set(self, qtbot):
        grid = MagicMock()
        parent = QtWidgets.QWidget()
        qtbot.addWidget(parent)
        overlay = self._cls(grid, parent)
        assert overlay.testAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        assert overlay.testAttribute(QtCore.Qt.WA_TranslucentBackground)

    def test_map_rect_delegates_to_grid(self, qtbot):
        grid = MagicMock()
        grid.mapFromScene.side_effect = lambda pt: QtCore.QPoint(int(pt.x()) + 10, int(pt.y()) + 20)
        parent = QtWidgets.QWidget()
        qtbot.addWidget(parent)
        overlay = self._cls(grid, parent)
        result = overlay._map_rect(QtCore.QRectF(0, 0, 100, 50))
        assert result.left() == 10
        assert result.top() == 20
        assert result.width() == 100
        assert result.height() == 50

    def test_map_rect_with_scroll_offset(self, qtbot):
        grid = MagicMock()
        grid.mapFromScene.side_effect = lambda pt: QtCore.QPoint(int(pt.x()) - 50, int(pt.y()) - 200)
        parent = QtWidgets.QWidget()
        qtbot.addWidget(parent)
        overlay = self._cls(grid, parent)
        result = overlay._map_rect(QtCore.QRectF(100, 300, 200, 150))
        assert result.left() == 50
        assert result.top() == 100
        assert result.width() == 200
        assert result.height() == 150

    def test_paint_no_crash_empty_state(self, qtbot):
        grid = MagicMock()
        grid.rects = None
        grid._rect_select_dragging = False
        grid._drop_preview_rect = None
        grid._half_pos = 2.0
        grid._selection_pen = QtGui.QPen()
        grid._selection_pen.setWidth(1)
        grid.items.selected_indices.return_value = set()
        grid.visible_indices = set()
        parent = QtWidgets.QWidget()
        qtbot.addWidget(parent)
        overlay = self._cls(grid, parent)
        overlay.resize(100, 100)
        pixmap = overlay.grab()
        assert not pixmap.isNull()


class TestGridViewOverlayIntegration:
    @pytest.fixture(autouse=True)
    def _import(self, qtbot):
        from wafer.app.viewer.grid.grid_view import GridView
        self.GridView = GridView

    def test_overlay_exists(self, qtbot):
        with patch('wafer.app.viewer.grid.grid_view.grid_resolver'):
            gv = self.GridView(MagicMock())
            qtbot.addWidget(gv)
            assert hasattr(gv, '_overlay')
            assert gv._overlay.parent() is gv.viewport()

    def test_overlay_transparent_for_mouse(self, qtbot):
        with patch('wafer.app.viewer.grid.grid_view.grid_resolver'):
            gv = self.GridView(MagicMock())
            qtbot.addWidget(gv)
            assert gv._overlay.testAttribute(QtCore.Qt.WA_TransparentForMouseEvents)

    def test_overlay_resizes_with_viewport(self, qtbot):
        with patch('wafer.app.viewer.grid.grid_view.grid_resolver'):
            gv = self.GridView(MagicMock())
            qtbot.addWidget(gv)
            gv.resize(400, 300)
            QtWidgets.QApplication.processEvents()
            assert gv._overlay.size() == gv.viewport().size()

    def test_eventfilter_paint_triggers_overlay_update(self, qtbot):
        with patch('wafer.app.viewer.grid.grid_view.grid_resolver'):
            gv = self.GridView(MagicMock())
            qtbot.addWidget(gv)
            gv._overlay.update = MagicMock()
            paint_event = QtCore.QEvent(QtCore.QEvent.Paint)
            gv.eventFilter(gv.viewport(), paint_event)
            gv._overlay.update.assert_called()


class TestOverlayCoordinateMapping:
    @pytest.fixture(autouse=True)
    def _import(self, qtbot):
        from wafer.app.viewer.grid.grid_view import GridView
        self.GridView = GridView

    def test_map_rect_identity_no_scroll(self, qtbot):
        with patch('wafer.app.viewer.grid.grid_view.grid_resolver'):
            gv = self.GridView(MagicMock())
            qtbot.addWidget(gv)
            gv.resize(800, 600)
            QtWidgets.QApplication.processEvents()
            gv._scene.setSceneRect(0, 0, 800, 600)
            scene_rect = QtCore.QRectF(10, 20, 100, 80)
            mapped = gv._overlay._map_rect(scene_rect)
            assert abs(mapped.left() - 10) < 2
            assert abs(mapped.top() - 20) < 2
            assert abs(mapped.width() - 100) < 2
            assert abs(mapped.height() - 80) < 2

    def test_map_rect_with_scroll(self, qtbot):
        with patch('wafer.app.viewer.grid.grid_view.grid_resolver'):
            gv = self.GridView(MagicMock())
            qtbot.addWidget(gv)
            gv.resize(800, 600)
            QtWidgets.QApplication.processEvents()
            gv._scene.setSceneRect(0, 0, 800, 3000)
            gv.verticalScrollBar().setValue(500)
            scene_rect = QtCore.QRectF(10, 600, 100, 80)
            mapped = gv._overlay._map_rect(scene_rect)
            assert abs(mapped.top() - 100) < 2
            assert abs(mapped.width() - 100) < 2
            assert abs(mapped.height() - 80) < 2

    def test_overlay_pos_stays_zero_after_scroll(self, qtbot):
        with patch('wafer.app.viewer.grid.grid_view.grid_resolver'):
            gv = self.GridView(MagicMock())
            qtbot.addWidget(gv)
            gv.show()
            gv.resize(800, 600)
            QtWidgets.QApplication.processEvents()
            gv._scene.setSceneRect(0, 0, 800, 5000)
            QtWidgets.QApplication.processEvents()
            for scroll_y in [0, 200, 1000, 3000]:
                gv.verticalScrollBar().setValue(scroll_y)
                QtWidgets.QApplication.processEvents()
                assert gv._overlay.pos() == QtCore.QPoint(0, 0), (
                    f"overlay pos drifted to {gv._overlay.pos()} at scroll={scroll_y}"
                )
                assert gv._overlay.size() == gv.viewport().size()

    def test_overlay_geometry_reset_in_paint(self, qtbot):
        with patch('wafer.app.viewer.grid.grid_view.grid_resolver'):
            gv = self.GridView(MagicMock())
            qtbot.addWidget(gv)
            gv.resize(800, 600)
            QtWidgets.QApplication.processEvents()
            gv._scene.setSceneRect(0, 0, 800, 5000)
            gv.verticalScrollBar().setValue(2000)
            QtWidgets.QApplication.processEvents()
            gv._overlay.grab()
            assert gv._overlay.pos() == QtCore.QPoint(0, 0)


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
        from wafer.app.viewer.grid.grid_view import GridView
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


class TestSetupCell:
    @pytest.fixture(autouse=True)
    def _import(self, qtbot):
        from wafer.app.viewer.grid.grid_view import GridView
        self.GridView = GridView

    def _make_fake(self, paths):
        fake = MagicMock()
        fake.items.paths = paths
        fake.widgets = {}
        fake._additional_widgets = {}
        fake._pipeline = MagicMock()
        fake._needs_reload = lambda item, size: self.GridView._needs_reload(fake, item, size)
        fake._content_size = lambda cell_size: self.GridView._content_size(fake, cell_size)
        return fake

    @patch('wafer.app.viewer.grid.grid_view.grid_resolver')
    def test_small_cached_triggers_pipeline(self, mock_resolver):
        mock_resolver.resolve_chain.return_value = []
        fake = self._make_fake(['img.jpg'])
        fake.rects = {0: QtCore.QRectF(0, 0, 600, 600)}
        fake.image_cache.get.return_value = _make_image(100, 100)
        fake.pixmap_item_pool.acquire.return_value = MockItem()

        self.GridView._setup_cell(fake, 0)

        fake._pipeline.schedule_render.assert_called_once()

    @patch('wafer.app.viewer.grid.grid_view.grid_resolver')
    def test_sufficient_cached_always_schedules_pipeline(self, mock_resolver):
        fake = self._make_fake(['img.jpg'])
        fake.rects = {0: QtCore.QRectF(0, 0, 200, 200)}
        fake.image_cache.get.return_value = _make_image(200, 200)
        fake.pixmap_item_pool.acquire.return_value = MockItem()

        self.GridView._setup_cell(fake, 0)

        fake._pipeline.schedule_render.assert_called_once()

    @patch('wafer.app.viewer.grid.grid_view.grid_resolver')
    def test_no_cache_starts_pipeline(self, mock_resolver):
        mock_resolver.resolve_chain.return_value = []
        fake = self._make_fake(['img.jpg'])
        fake.rects = {0: QtCore.QRectF(0, 0, 200, 200)}
        fake.image_cache.get.return_value = None
        fake.pixmap_item_pool.acquire.return_value = MockItem()

        self.GridView._setup_cell(fake, 0)

        fake._pipeline.schedule_render.assert_called_once()

    @patch('wafer.app.viewer.grid.grid_view.grid_resolver')
    def test_small_cached_sets_image_before_pipeline(self, mock_resolver):
        mock_resolver.resolve_chain.return_value = []
        fake = self._make_fake(['img.jpg'])
        fake.rects = {0: QtCore.QRectF(0, 0, 600, 600)}
        fake.image_cache.get.return_value = _make_image(100, 100)
        mock_item = MockItem()
        fake.pixmap_item_pool.acquire.return_value = mock_item

        self.GridView._setup_cell(fake, 0)

        assert mock_item.current_path == 'img.jpg'
        fake._pipeline.schedule_render.assert_called_once()

    @patch('wafer.app.viewer.grid.grid_view.grid_resolver')
    def test_existing_widget_not_recreated(self, mock_resolver):
        mock_resolver.resolve_chain.return_value = []
        fake = self._make_fake(['img.jpg'])
        rect = QtCore.QRectF(0, 0, 200, 200)
        fake.rects = {0: rect}
        existing = MagicMock()
        existing.geometry.return_value = rect
        fake.widgets = {0: existing}

        self.GridView._setup_cell(fake, 0)

        fake.pixmap_item_pool.acquire.assert_not_called()
        fake._pipeline.schedule_render.assert_not_called()

    @patch('wafer.app.viewer.grid.grid_view.grid_resolver')
    def test_content_size_passed_to_pipeline(self, mock_resolver):
        mock_resolver.resolve_chain.return_value = []
        fake = self._make_fake(['img.jpg'])
        fake.rects = {0: QtCore.QRectF(0, 0, 200, 200)}
        fake.image_cache.get.return_value = None
        fake.pixmap_item_pool.acquire.return_value = MockItem()

        self.GridView._setup_cell(fake, 0)

        call_args = fake._pipeline.schedule_render.call_args
        size = call_args[0][2]
        expected = self.GridView._content_size(fake, fake.rects[0].size())
        assert size == expected


class TestSetupCellResize:
    @pytest.fixture(autouse=True)
    def _import(self, qtbot):
        from wafer.app.viewer.grid.grid_view import GridView
        self.GridView = GridView

    @patch('wafer.app.viewer.grid.grid_view.grid_resolver')
    def test_resize_then_scroll_triggers_pipeline(self, mock_resolver):
        mock_resolver.resolve_chain.return_value = []
        fake = MagicMock()
        fake.items.paths = ['a.jpg']
        fake.widgets = {}
        fake._additional_widgets = {}
        fake._pipeline = MagicMock()
        fake._needs_reload = lambda item, size: self.GridView._needs_reload(fake, item, size)
        fake._content_size = lambda cell_size: self.GridView._content_size(fake, cell_size)

        small_rect = QtCore.QRectF(0, 0, 200, 200)
        fake.rects = {0: small_rect}
        fake.image_cache.get.return_value = None
        fake.pixmap_item_pool.acquire.return_value = MockItem()

        self.GridView._setup_cell(fake, 0)
        assert fake._pipeline.schedule_render.call_count == 1

        fake._pipeline.schedule_render.reset_mock()

        big_rect = QtCore.QRectF(0, 0, 600, 600)
        fake.rects = {0: big_rect}
        fake.widgets = {}
        small_cached = _make_image(200 - LOADER_MARGIN, 200 - LOADER_MARGIN)
        fake.image_cache.get.return_value = small_cached
        fake.pixmap_item_pool.acquire.return_value = MockItem()

        self.GridView._setup_cell(fake, 0)

        fake._pipeline.schedule_render.assert_called_once()


class TestSetupCellAdditionalWidget:
    @pytest.fixture(autouse=True)
    def _import(self, qtbot):
        from wafer.app.viewer.grid.grid_view import GridView
        self.GridView = GridView

    def _make_fake(self, paths):
        fake = MagicMock()
        fake.items.paths = paths
        fake.widgets = {}
        fake._additional_widgets = {}
        fake._pipeline = MagicMock()
        fake._needs_reload = lambda item, size: self.GridView._needs_reload(fake, item, size)
        fake._content_size = lambda cell_size: self.GridView._content_size(fake, cell_size)
        return fake

    @patch('wafer.app.viewer.grid.grid_view.grid_resolver')
    def test_widget_class_plugin_creates_pixmap_item_and_defers(self, mock_resolver):
        fake = self._make_fake(['test.mp4'])
        fake.rects = {0: QtCore.QRectF(0, 0, 200, 200)}
        fake.image_cache.get.return_value = None
        mock_item = MockItem()
        fake.pixmap_item_pool.acquire.return_value = mock_item

        self.GridView._setup_cell(fake, 0)

        fake.pixmap_item_pool.acquire.assert_called_once()
        assert 0 in fake.widgets
        assert 0 not in fake._additional_widgets
        fake._pipeline.schedule_render.assert_called_once()
        fake.additional_pool.acquire.assert_not_called()

    @patch('wafer.app.viewer.grid.grid_view.grid_resolver')
    def test_existing_additional_widget_not_recreated(self, mock_resolver):
        from wafer.plugin.grid.base import WidgetGridPlugin

        class _StubWidgetPlugin(WidgetGridPlugin):
            NAME = 'test_vid'
            EXTENSIONS = ('.mp4',)
            WIDGET_CLASS = MagicMock

        mock_resolver.resolve_chain.return_value = [_StubWidgetPlugin]
        fake = self._make_fake(['test.mp4'])
        fake.rects = {0: QtCore.QRectF(0, 0, 200, 200)}
        fake._additional_widgets = {0: MagicMock()}

        self.GridView._setup_cell(fake, 0)

        fake.additional_pool.acquire.assert_not_called()
        fake._pipeline.schedule_render.assert_not_called()


class TestRecycleWidget:
    @pytest.fixture(autouse=True)
    def _import(self, qtbot):
        from wafer.app.viewer.grid.grid_view import GridView
        self.GridView = GridView

    def test_recycle_pixmap_item(self):
        fake = MagicMock()
        fake.widgets = {0: MagicMock()}
        fake._additional_widgets = {}
        fake._pipeline = MagicMock()

        self.GridView._recycle_widget(fake, 0)

        fake.pixmap_item_pool.release.assert_called_once()
        assert 0 not in fake.widgets
        fake._pipeline.cancel_index.assert_called_once_with(0)

    def test_recycle_additional_widget_calls_unbind(self):
        fake = MagicMock()
        fake.widgets = {}
        widget = MagicMock()
        fake._additional_widgets = {0: widget}
        fake._pipeline = MagicMock()

        self.GridView._recycle_widget(fake, 0)

        fake._notifier.unbind.assert_called_once_with(0, widget)
        fake.additional_pool.release.assert_called_once_with(widget)
        assert 0 not in fake._additional_widgets
        fake._pipeline.cancel_index.assert_called_once_with(0)

    def test_recycle_cancels_pipeline_task(self):
        fake = MagicMock()
        fake.widgets = {}
        fake._additional_widgets = {}
        fake._pipeline = MagicMock()

        self.GridView._recycle_widget(fake, 0)

        fake._pipeline.cancel_index.assert_called_once_with(0)


class TestAutoScroll:
    def test_start_auto_scroll_stores_base_speed(self):
        gv = MagicMock()
        gv._scroll_speed = 100
        gv._autoscroll_base_speed = 50
        gv._speed_callback = None
        anim = MagicMock()
        gv._auto_scroll_anim = anim
        bar = MagicMock()
        bar.value.return_value = 0
        bar.minimum.return_value = 0
        bar.maximum.return_value = 10000
        gv._primary_bar.return_value = bar
        gv._is_primary_reversed.return_value = False

        from wafer.app.viewer.grid.grid_view import GridView
        GridView.start_auto_scroll(gv, speed=30, base_speed=100)
        assert gv._autoscroll_base_speed == 100
        assert gv._scroll_speed == 30

    def test_start_auto_scroll_default_base_speed(self):
        gv = MagicMock()
        gv._scroll_speed = 100
        gv._autoscroll_base_speed = 50
        gv._speed_callback = None
        anim = MagicMock()
        gv._auto_scroll_anim = anim
        bar = MagicMock()
        bar.value.return_value = 0
        bar.minimum.return_value = 0
        bar.maximum.return_value = 10000
        gv._primary_bar.return_value = bar
        gv._is_primary_reversed.return_value = False

        from wafer.app.viewer.grid.grid_view import GridView
        GridView.start_auto_scroll(gv, speed=25)
        assert gv._autoscroll_base_speed == 50

    def test_get_adjusted_scroll_speed_scales_with_base(self):
        gv = MagicMock()
        gv.base_height = 100
        gv.screen_width = 1920

        from wafer.app.viewer.grid.grid_view import GridView
        slow = GridView.get_adjusted_scroll_speed(gv, 10)
        fast = GridView.get_adjusted_scroll_speed(gv, 100)
        assert fast > slow

    def test_speed_callback_uses_base_speed_attribute(self):
        gv = MagicMock()
        gv._autoscroll_base_speed = 200
        gv.base_height = 100
        gv.screen_width = 1920

        from wafer.app.viewer.grid.grid_view import GridView
        expected = GridView.get_adjusted_scroll_speed(gv, 200)

        callback = lambda: GridView.get_adjusted_scroll_speed(gv, gv._autoscroll_base_speed)
        assert callback() == expected


class TestFindCenterIndexEffectiveScroll:
    def test_uses_scroll_target_when_animating(self):
        from wafer.app.viewer.grid.grid_view import GridView
        from wafer.app.viewer.grid.calc_layout import LayoutData

        rects_raw = [
            QtCore.QRect(0, 0, 200, 100),
            QtCore.QRect(200, 0, 200, 100),
            QtCore.QRect(0, 110, 200, 100),
            QtCore.QRect(200, 110, 200, 100),
            QtCore.QRect(0, 220, 200, 100),
        ]
        layout = LayoutData(rects_raw, 320, True)

        gv = MagicMock()
        gv.rects = layout
        gv._hz = True
        gv.spacing = 10
        gv._primary_viewport_size.return_value = 200
        gv._effective_scroll_top.return_value = 110
        gv.mapToScene.return_value = QtCore.QPointF(100, 50)

        idx = GridView._find_center_index(gv)
        assert idx in (2, 3)

    def test_uses_actual_pos_when_not_animating(self):
        from wafer.app.viewer.grid.grid_view import GridView
        from wafer.app.viewer.grid.calc_layout import LayoutData

        rects_raw = [
            QtCore.QRect(0, 0, 200, 100),
            QtCore.QRect(200, 0, 200, 100),
            QtCore.QRect(0, 110, 200, 100),
        ]
        layout = LayoutData(rects_raw, 210, True)

        gv = MagicMock()
        gv.rects = layout
        gv._hz = True
        gv.spacing = 10
        gv._primary_viewport_size.return_value = 200
        gv._effective_scroll_top.return_value = 0
        gv.mapToScene.return_value = QtCore.QPointF(100, 50)

        idx = GridView._find_center_index(gv)
        assert idx in (0, 1)

    def test_scroll_row_chains_through_rows(self):
        from wafer.app.viewer.grid.grid_view import GridView
        from wafer.app.viewer.grid.calc_layout import LayoutData

        rects_raw = [
            QtCore.QRect(0, 0, 200, 100),
            QtCore.QRect(200, 0, 200, 100),
            QtCore.QRect(0, 110, 200, 100),
            QtCore.QRect(200, 110, 200, 100),
            QtCore.QRect(0, 220, 200, 100),
            QtCore.QRect(200, 220, 200, 100),
        ]
        layout = LayoutData(rects_raw, 320, True)

        gv = MagicMock()
        gv.rects = layout
        gv._hz = True
        gv.spacing = 10
        gv._scroll_anim = None
        gv._scroll_target = 0
        gv._primary_viewport_size.return_value = 200
        gv._is_primary_reversed.return_value = False
        gv._is_center_anchor.return_value = False
        gv.mapToScene.return_value = QtCore.QPointF(100, 50)
        gv._effective_scroll_top.return_value = 0

        targets = []

        def capture_scroll_to(target, animated=True):
            targets.append(target)
            gv._scroll_target = target
            gv._effective_scroll_top.return_value = target

        gv._scroll_to = capture_scroll_to
        gv._find_center_index = lambda: GridView._find_center_index(gv)

        GridView._scroll_row(gv, forward=True, animated=False)
        GridView._scroll_row(gv, forward=True, animated=False)

        assert len(targets) == 2
        assert targets[1] > targets[0]
