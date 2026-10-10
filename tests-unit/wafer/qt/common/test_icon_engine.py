import pytest
from PySide6.QtCore import QRectF, QSize
from PySide6.QtGui import QColor, QPainter, QPixmap


@pytest.fixture(autouse=True)
def _ensure_qapp(qtbot):
    pass


def _assert_logical_size(pm: QPixmap, expected: int):
    logical = pm.deviceIndependentSize().toSize()
    assert logical.width() == expected
    assert logical.height() == expected


class TestThemedIcon:
    def test_unknown_key_returns_null_icon(self):
        from wafer.qt.common.icon_engine import themed_icon

        icon = themed_icon("nonexistent")
        assert icon.isNull()


class TestIconDraw:
    def test_unknown_key_noop(self):
        from wafer.qt.common.icon_engine import icon_draw

        pm = QPixmap(32, 32)
        p = QPainter(pm)
        icon_draw("nonexistent", p, QRectF(0, 0, 32, 32), QColor(200, 200, 200))
        p.end()


class TestAllRegisteredIcons:
    def test_every_registered_icon_renders(self):
        from wafer.qt.common.icon_engine import _REGISTRY, icon_draw, themed_icon

        assert _REGISTRY
        for key in _REGISTRY:
            icon = themed_icon(key)
            assert not icon.isNull(), key
            for sz in (16, 24, 48):
                _assert_logical_size(icon.pixmap(QSize(sz, sz)), sz)
            for sz in (32, 8):
                pm = QPixmap(sz, sz)
                p = QPainter(pm)
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                icon_draw(key, p, QRectF(0, 0, sz, sz), QColor(200, 200, 200))
                p.end()


class TestPadding:
    def test_padding_clamped(self):
        from wafer.qt.common.icon_engine import _REGISTRY, _ThemedIconEngine

        fn, _ = _REGISTRY["gear"]
        engine = _ThemedIconEngine(fn, padding=0.8)
        assert engine._padding == 0.5
        engine2 = _ThemedIconEngine(fn, padding=-0.1)
        assert engine2._padding == 0.0

    def test_margins_render(self):
        from wafer.qt.common.icon_engine import themed_icon

        for margin in (0.0, 0.1, 0.2, 0.3, 0.35):
            icon = themed_icon("folder_plus", margin=margin)
            assert not icon.isNull()
            _assert_logical_size(icon.pixmap(QSize(32, 32)), 32)
