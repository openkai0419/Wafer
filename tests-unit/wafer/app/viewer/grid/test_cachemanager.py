import pytest
from PySide6 import QtWidgets
from wafer.app.viewer.grid.cachemanager import AdditionalWidgetPool
from wafer.plugin.grid.handler import grid_resolver
from wafer.plugin.grid.base import WidgetGridPlugin


class TestFadePixmapItemRendering:
    @pytest.fixture(autouse=True)
    def setup(self, qapp):
        from wafer.app.viewer.grid.cachemanager import FadePixmapItem
        from PySide6 import QtWidgets, QtCore

        scene = QtWidgets.QGraphicsScene()
        self.item = FadePixmapItem()
        scene.addItem(self.item)
        self.scene = scene
        yield
        scene.clear()

    def test_tooltip_shows_the_path_as_plain_text(self):
        from PySide6 import QtGui

        path = 'C:/a b/x.zip::<img src="//host/share/p.png"> & <b>y</b>.png'
        img = QtGui.QImage(10, 10, QtGui.QImage.Format_ARGB32)
        self.item.set_image(img, path)
        doc = QtGui.QTextDocument()
        doc.setHtml(self.item.toolTip())
        assert doc.toPlainText().replace("\xa0", " ") == path

    def test_landscape_in_square_cell(self):
        from PySide6 import QtGui, QtCore

        img = QtGui.QImage(200, 100, QtGui.QImage.Format_ARGB32)
        img.fill(QtGui.QColor(255, 0, 0))
        self.item.setGeometry(QtCore.QRect(0, 0, 200, 200))
        self.item.set_image(img, "landscape_test")
        target = QtGui.QPixmap(200, 200)
        target.fill(QtGui.QColor(0, 0, 0, 0))
        painter = QtGui.QPainter(target)
        self.item.paint(painter, None)
        painter.end()
        result = target.toImage()
        top_pixel = result.pixelColor(100, 10)
        mid_pixel = result.pixelColor(100, 100)
        bot_pixel = result.pixelColor(100, 190)
        assert top_pixel.red() == 255 and top_pixel.alpha() == 255
        assert mid_pixel.red() == 255 and mid_pixel.alpha() == 255
        assert bot_pixel.red() == 255 and bot_pixel.alpha() == 255

    def test_portrait_in_square_cell(self):
        from PySide6 import QtGui, QtCore

        img = QtGui.QImage(100, 200, QtGui.QImage.Format_ARGB32)
        img.fill(QtGui.QColor(0, 0, 255))
        self.item.setGeometry(QtCore.QRect(0, 0, 200, 200))
        self.item.set_image(img, "portrait_test")
        target = QtGui.QPixmap(200, 200)
        target.fill(QtGui.QColor(0, 0, 0, 0))
        painter = QtGui.QPainter(target)
        self.item.paint(painter, None)
        painter.end()
        result = target.toImage()
        left_pixel = result.pixelColor(10, 100)
        mid_pixel = result.pixelColor(100, 100)
        right_pixel = result.pixelColor(190, 100)
        assert left_pixel.blue() == 255 and left_pixel.alpha() == 255
        assert mid_pixel.blue() == 255 and mid_pixel.alpha() == 255
        assert right_pixel.blue() == 255 and right_pixel.alpha() == 255

    def test_exact_aspect_fills_cell(self):
        from PySide6 import QtGui, QtCore

        img = QtGui.QImage(200, 100, QtGui.QImage.Format_ARGB32)
        img.fill(QtGui.QColor(255, 0, 0))
        self.item.setGeometry(QtCore.QRect(0, 0, 200, 100))
        self.item.set_image(img, "exact_test")
        target = QtGui.QPixmap(200, 100)
        target.fill(QtGui.QColor(0, 0, 0, 0))
        painter = QtGui.QPainter(target)
        self.item.paint(painter, None)
        painter.end()
        result = target.toImage()
        top_pixel = result.pixelColor(100, 5)
        mid_pixel = result.pixelColor(100, 50)
        bot_pixel = result.pixelColor(100, 95)
        assert top_pixel.red() == 255 and top_pixel.alpha() == 255
        assert mid_pixel.red() == 255 and mid_pixel.alpha() == 255
        assert bot_pixel.red() == 255 and bot_pixel.alpha() == 255

    def test_with_loaded_image_file(self, tmp_path):
        from PySide6 import QtGui, QtCore
        from PIL import Image as PILImage
        from extensions.image.loader import load_image

        cell_w, cell_h = 200, 200
        img_path = str(tmp_path / "wide.png")
        PILImage.new("RGB", (400, 100), (0, 255, 0)).save(img_path)
        loaded = load_image(img_path, QtCore.QSize(cell_w, cell_h))
        assert loaded is not None
        assert loaded.width() >= cell_w or loaded.height() >= cell_h
        aspect_ratio = loaded.width() / loaded.height()
        assert abs(aspect_ratio - 4.0) < 0.1

        self.item.setGeometry(QtCore.QRect(0, 0, cell_w, cell_h))
        self.item.set_image(loaded, img_path)
        target = QtGui.QPixmap(cell_w, cell_h)
        target.fill(QtGui.QColor(0, 0, 0, 0))
        painter = QtGui.QPainter(target)
        self.item.paint(painter, None)
        painter.end()
        result = target.toImage()
        center = result.pixelColor(100, 100)
        assert center.green() == 255 and center.alpha() == 255
        top = result.pixelColor(100, 5)
        assert top.green() == 255 and top.alpha() == 255
        bottom = result.pixelColor(100, 195)
        assert bottom.green() == 255 and bottom.alpha() == 255


class _DummyWidget(QtWidgets.QWidget):
    pass


class _DummyGridPlugin(WidgetGridPlugin):
    NAME = "test_dummy"
    EXTENSIONS = (".dummy",)
    PRIORITY = 50
    WIDGET_CLASS = _DummyWidget

    def render(self, path, widget, size=None):
        pass


@pytest.fixture
def additional_pool(qtbot):
    from unittest.mock import MagicMock

    resolver = MagicMock()
    resolver.registry.get.return_value = _DummyGridPlugin
    pool = AdditionalWidgetPool(resolver)
    yield pool
    pool.reset()


def test_additional_pool_acquire_returns_widget(additional_pool, qtbot):
    parent = QtWidgets.QWidget()
    widget = additional_pool.acquire("test_dummy", parent)
    assert widget is not None
    assert isinstance(widget, _DummyWidget)
    assert widget.parent() is parent


def test_additional_pool_acquire_unknown_returns_none(qtbot):
    from unittest.mock import MagicMock

    resolver = MagicMock()
    resolver.registry.get.return_value = None
    pool = AdditionalWidgetPool(resolver)
    parent = QtWidgets.QWidget()
    assert pool.acquire("nonexistent", parent) is None


def test_additional_pool_release_and_reuse(additional_pool, qtbot):
    parent = QtWidgets.QWidget()
    w1 = additional_pool.acquire("test_dummy", parent)
    additional_pool.release(w1)
    w2 = additional_pool.acquire("test_dummy", parent)
    assert w1 is w2


def test_additional_pool_plugin_name_of(additional_pool, qtbot):
    parent = QtWidgets.QWidget()
    w = additional_pool.acquire("test_dummy", parent)
    assert additional_pool.plugin_name_of(w) == "test_dummy"
    additional_pool.release(w)
    assert additional_pool.plugin_name_of(w) is None


def test_additional_pool_reset(additional_pool, qtbot):
    parent = QtWidgets.QWidget()
    additional_pool.acquire("test_dummy", parent)
    additional_pool.acquire("test_dummy", parent)
    additional_pool.reset()
    assert len(additional_pool._in_use) == 0
    assert all(len(v) == 0 for v in additional_pool._pools.values())


def test_additional_pool_reset_calls_cleanup(qtbot):
    from unittest.mock import MagicMock

    class _CleanableWidget(QtWidgets.QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self.cleanup = MagicMock()

    class _CleanPlugin(WidgetGridPlugin):
        NAME = "test_clean"
        EXTENSIONS = (".clean",)
        PRIORITY = 50
        WIDGET_CLASS = _CleanableWidget

    resolver = MagicMock()
    resolver.registry.get.return_value = _CleanPlugin
    pool = AdditionalWidgetPool(resolver)
    parent = QtWidgets.QWidget()
    w = pool.acquire("test_clean", parent)
    pool.reset()
    w.cleanup.assert_called_once()


def test_additional_pool_warm_up(qtbot):
    from unittest.mock import MagicMock

    resolver = MagicMock()
    resolver.registry.list_all.return_value = [_DummyGridPlugin]
    resolver.registry.get.return_value = _DummyGridPlugin
    pool = AdditionalWidgetPool(resolver)
    parent = QtWidgets.QWidget()
    pool.warm_up(parent)
    assert "test_dummy" in pool._pools
    assert len(pool._pools["test_dummy"]) == 1
    assert isinstance(pool._pools["test_dummy"][0], _DummyWidget)


def test_additional_pool_warm_up_skips_non_widget_plugins(qtbot):
    from unittest.mock import MagicMock
    from wafer.plugin.grid.base import BaseGridPlugin

    class _NonWidgetPlugin(BaseGridPlugin):
        NAME = "non_widget"
        EXTENSIONS = (".jpg",)
        PRIORITY = 50

    resolver = MagicMock()
    resolver.registry.list_all.return_value = [_NonWidgetPlugin]
    pool = AdditionalWidgetPool(resolver)
    parent = QtWidgets.QWidget()
    pool.warm_up(parent)
    assert len(pool._pools) == 0


def test_additional_pool_warm_up_skips_existing(qtbot):
    from unittest.mock import MagicMock

    resolver = MagicMock()
    resolver.registry.list_all.return_value = [_DummyGridPlugin]
    resolver.registry.get.return_value = _DummyGridPlugin
    pool = AdditionalWidgetPool(resolver)
    parent = QtWidgets.QWidget()
    pool.warm_up(parent)
    pool.warm_up(parent)
    assert len(pool._pools["test_dummy"]) == 1


def test_additional_pool_size_and_in_use_count(qtbot):
    from unittest.mock import MagicMock

    resolver = MagicMock()
    resolver.registry.get.return_value = _DummyGridPlugin
    pool = AdditionalWidgetPool(resolver)
    parent = QtWidgets.QWidget()
    assert pool.pool_size("test_dummy") == 0
    assert pool.in_use_count("test_dummy") == 0
    w = pool.acquire("test_dummy", parent)
    assert pool.in_use_count("test_dummy") == 1
    pool.release(w)
    assert pool.pool_size("test_dummy") == 1
    assert pool.in_use_count("test_dummy") == 0
    pool.reset()
