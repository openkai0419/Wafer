import pytest
from PySide6.QtCore import QRectF, QSize
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap


@pytest.fixture(autouse=True)
def _ensure_qapp(qtbot):
    pass


def _assert_logical_size(pm: QPixmap, expected: int):
    logical = pm.deviceIndependentSize().toSize()
    assert logical.width() == expected
    assert logical.height() == expected


class TestThemedIcon:
    def test_returns_qicon(self):
        from wafer.core.qt.icon_engine import themed_icon

        icon = themed_icon("gear")
        assert isinstance(icon, QIcon)
        assert not icon.isNull()

    def test_unknown_key_returns_null_icon(self):
        from wafer.core.qt.icon_engine import themed_icon

        icon = themed_icon("nonexistent")
        assert icon.isNull()

    def test_pixmap_generation(self):
        from wafer.core.qt.icon_engine import themed_icon

        icon = themed_icon("play")
        pm = icon.pixmap(QSize(32, 32))
        _assert_logical_size(pm, 32)


class TestIconDraw:
    def test_draw_invokes_without_error(self):
        from wafer.core.qt.icon_engine import icon_draw

        pm = QPixmap(32, 32)
        p = QPainter(pm)
        icon_draw("gear", p, QRectF(0, 0, 32, 32), QColor(200, 200, 200))
        p.end()

    def test_unknown_key_noop(self):
        from wafer.core.qt.icon_engine import icon_draw

        pm = QPixmap(32, 32)
        p = QPainter(pm)
        icon_draw("nonexistent", p, QRectF(0, 0, 32, 32), QColor(200, 200, 200))
        p.end()


ALL_KEYS = [
    "gear",
    "gear_small",
    "folder_plus",
    "subfolder",
    "fullscreen",
    "window",
    "fit_cover",
    "fit_contain",
    "plus",
    "minus",
    "play",
    "pause",
    "volume",
    "muted",
    "cross",
    "check",
    "chevron_down",
    "chevron_right",
    "sort",
    "query",
    "menu",
    "layout_edit",
    "refresh",
    "history",
    "save",
    "section_tag",
    "section_meta",
    "section_root",
]


class TestAllRegisteredIcons:
    @pytest.mark.parametrize("key", ALL_KEYS)
    def test_icon_not_null(self, key):
        from wafer.core.qt.icon_engine import themed_icon

        assert not themed_icon(key).isNull()

    @pytest.mark.parametrize("key", ALL_KEYS)
    def test_draw_without_error(self, key):
        from wafer.core.qt.icon_engine import icon_draw

        pm = QPixmap(32, 32)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        icon_draw(key, p, QRectF(0, 0, 32, 32), QColor(200, 200, 200))
        p.end()

    @pytest.mark.parametrize("key", ALL_KEYS)
    def test_draw_at_small_size(self, key):
        from wafer.core.qt.icon_engine import icon_draw

        pm = QPixmap(8, 8)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        icon_draw(key, p, QRectF(0, 0, 8, 8), QColor(200, 200, 200))
        p.end()

    @pytest.mark.parametrize("key", ALL_KEYS)
    def test_pixmap_at_multiple_sizes(self, key):
        from wafer.core.qt.icon_engine import themed_icon

        icon = themed_icon(key)
        for sz in [16, 24, 48]:
            pm = icon.pixmap(QSize(sz, sz))
            _assert_logical_size(pm, sz)


class TestPadding:
    def test_default_padding(self):
        from wafer.core.qt.icon_engine import themed_icon

        icon = themed_icon("gear")
        assert not icon.isNull()
        pm = icon.pixmap(QSize(32, 32))
        _assert_logical_size(pm, 32)

    def test_zero_margin(self):
        from wafer.core.qt.icon_engine import themed_icon

        icon = themed_icon("gear", margin=0.0)
        assert not icon.isNull()

    def test_large_margin(self):
        from wafer.core.qt.icon_engine import themed_icon

        icon = themed_icon("gear", margin=0.35)
        pm = icon.pixmap(QSize(32, 32))
        _assert_logical_size(pm, 32)

    def test_padding_clamped(self):
        from wafer.core.qt.icon_engine import themed_icon, _ThemedIconEngine
        from wafer.core.qt.icon_engine import _REGISTRY

        fn, _ = _REGISTRY["gear"]
        engine = _ThemedIconEngine(fn, padding=0.8)
        assert engine._padding == 0.5
        engine2 = _ThemedIconEngine(fn, padding=-0.1)
        assert engine2._padding == 0.0

    @pytest.mark.parametrize("margin", [0.0, 0.1, 0.2, 0.3])
    def test_various_margins_render(self, margin):
        from wafer.core.qt.icon_engine import themed_icon

        icon = themed_icon("folder_plus", margin=margin)
        pm = icon.pixmap(QSize(32, 32))
        _assert_logical_size(pm, 32)
