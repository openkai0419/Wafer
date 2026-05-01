import pytest
from unittest.mock import MagicMock, patch
from PySide6 import QtCore, QtGui


class TestAnimatedViewerWidgetInit:
    def test_initial_state(self, qtbot):
        from extensions.animated.viewer_widget import AnimatedViewerWidget

        w = AnimatedViewerWidget()
        qtbot.addWidget(w)
        assert w._path == ""
        assert w._frames == []
        assert w._delays == []
        assert w._frame_index == 0
        assert w._playing is False
        assert w.cover_mode is False

    def test_set_cover_mode(self, qtbot):
        from extensions.animated.viewer_widget import AnimatedViewerWidget

        w = AnimatedViewerWidget()
        qtbot.addWidget(w)
        assert w.cover_mode is False
        w.set_cover_mode(True)
        assert w.cover_mode is True
        w.set_cover_mode(False)
        assert w.cover_mode is False

    def test_toggle_fit_mode(self, qtbot):
        from extensions.animated.viewer_widget import AnimatedViewerWidget

        w = AnimatedViewerWidget()
        qtbot.addWidget(w)
        assert w.cover_mode is False
        w.toggle_fit_mode()
        assert w.cover_mode is True
        w.toggle_fit_mode()
        assert w.cover_mode is False

    def test_has_command_mixin(self):
        from extensions.animated.viewer_widget import AnimatedViewerWidget
        from wafer.core.commands.bridge import ActionKit

        assert issubclass(AnimatedViewerWidget, ActionKit.UIMixin)


class TestAnimatedViewerWidgetClear:
    def test_clear_resets_state(self, qtbot):
        from extensions.animated.viewer_widget import AnimatedViewerWidget

        w = AnimatedViewerWidget()
        qtbot.addWidget(w)
        w._path = "test.gif"
        w._frame_index = 5
        w.clear()
        assert w._path == ""
        assert w._frames == []
        assert w._delays == []
        assert w._frame_index == 0
        assert w._playing is False


class TestAnimatedViewerWidgetActivate:
    def test_activate_starts_if_multiframe(self, qtbot):
        from extensions.animated.viewer_widget import AnimatedViewerWidget

        w = AnimatedViewerWidget()
        qtbot.addWidget(w)
        pix = QtGui.QPixmap(10, 10)
        w._frames = [pix, pix]
        w._delays = [100, 100]
        w.activate()
        assert w._playing is True
        w.stop()

    def test_activate_no_start_single_frame(self, qtbot):
        from extensions.animated.viewer_widget import AnimatedViewerWidget

        w = AnimatedViewerWidget()
        qtbot.addWidget(w)
        pix = QtGui.QPixmap(10, 10)
        w._frames = [pix]
        w._delays = [100]
        w.activate()
        assert w._playing is False

    def test_deactivate_stops(self, qtbot):
        from extensions.animated.viewer_widget import AnimatedViewerWidget

        w = AnimatedViewerWidget()
        qtbot.addWidget(w)
        pix = QtGui.QPixmap(10, 10)
        w._frames = [pix, pix]
        w._delays = [100, 100]
        w.start()
        assert w._playing is True
        w.deactivate()
        assert w._playing is False


class TestAnimatedViewerWidgetAdvance:
    def test_advance_cycles_frames(self, qtbot):
        from extensions.animated.viewer_widget import AnimatedViewerWidget

        w = AnimatedViewerWidget()
        qtbot.addWidget(w)
        pix1 = QtGui.QPixmap(10, 10)
        pix2 = QtGui.QPixmap(10, 10)
        w._frames = [pix1, pix2]
        w._delays = [32, 32]
        w._playing = True
        w._accumulated = 0
        with patch.object(type(w), "update"):
            w.advance(16)
            assert w._frame_index == 0
            w.advance(16)
            assert w._frame_index == 1
            w.advance(16)
            assert w._frame_index == 1
            w.advance(16)
            assert w._frame_index == 0


class TestAnimatedViewerWidgetPaint:
    def test_paint_empty_frames_no_crash(self, qtbot):
        from extensions.animated.viewer_widget import AnimatedViewerWidget

        w = AnimatedViewerWidget()
        qtbot.addWidget(w)
        w.resize(100, 100)
        w.repaint()

    def test_paint_with_frame(self, qtbot):
        from extensions.animated.viewer_widget import AnimatedViewerWidget

        w = AnimatedViewerWidget()
        qtbot.addWidget(w)
        pix = QtGui.QPixmap(50, 50)
        pix.fill(QtGui.QColor("red"))
        w._frames = [pix]
        w._delays = [100]
        w.resize(100, 100)
        w.repaint()

    def test_paint_cover_mode(self, qtbot):
        from extensions.animated.viewer_widget import AnimatedViewerWidget

        w = AnimatedViewerWidget()
        qtbot.addWidget(w)
        pix = QtGui.QPixmap(50, 50)
        pix.fill(QtGui.QColor("red"))
        w._frames = [pix]
        w._delays = [100]
        w.set_cover_mode(True)
        w.resize(100, 80)
        w.repaint()


class TestExtendContext:
    def test_returns_path(self, qtbot):
        from extensions.animated.viewer_widget import AnimatedViewerWidget

        w = AnimatedViewerWidget()
        qtbot.addWidget(w)
        w._path = "/test.gif"
        ctx = w.extend_context(None, None)
        assert ctx == {"path": "/test.gif", "paths": ["/test.gif"], "source": "/test.gif", "sources": ["/test.gif"]}

    def test_returns_empty_paths_when_no_path(self, qtbot):
        from extensions.animated.viewer_widget import AnimatedViewerWidget

        w = AnimatedViewerWidget()
        qtbot.addWidget(w)
        ctx = w.extend_context(None, None)
        assert ctx == {"path": "", "paths": [], "source": None, "sources": []}


class TestViewerCache:
    def test_viewer_cache_is_separate_from_grid(self):
        from extensions.animated._common import _viewer_cache, _grid_cache

        assert _viewer_cache is not _grid_cache

    def test_viewer_cache_small_capacity(self):
        from extensions.animated._common import _viewer_cache

        assert _viewer_cache._max <= 16
