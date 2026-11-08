from types import SimpleNamespace
from unittest.mock import patch
from PySide6 import QtGui


class TestAnimatedViewerWidgetInit:
    def test_toggle_fit_mode(self, qtbot):
        from extensions.animated.viewer_widget import AnimatedViewerWidget

        w = AnimatedViewerWidget()
        qtbot.addWidget(w)
        assert w.cover_mode is False
        w.toggle_fit_mode()
        assert w.cover_mode is True
        w.toggle_fit_mode()
        assert w.cover_mode is False


class TestAnimatedViewerWidgetGridPreview:
    def _widget(self, qtbot):
        from extensions.animated._common import _grid_cache, _viewer_cache
        from extensions.animated.viewer_widget import AnimatedViewerWidget

        _grid_cache.clear()
        _viewer_cache.clear()
        w = AnimatedViewerWidget()
        qtbot.addWidget(w)
        w._dispatcher.post = lambda *args, **kwargs: None
        return w, _grid_cache, _viewer_cache

    def test_grid_frames_play_while_the_original_decodes(self, qtbot):
        w, grid_cache, _ = self._widget(qtbot)
        frames = [QtGui.QPixmap(10, 10), QtGui.QPixmap(10, 10)]
        grid_cache.put("a.gif", frames, [100, 100])
        w.load(SimpleNamespace(render_path="a.gif"))
        assert w._frames is frames and w._playing is True
        w.stop()
        grid_cache.clear()

    def test_decoded_frames_replace_the_preview_at_the_same_position(self, qtbot):
        w, grid_cache, _ = self._widget(qtbot)
        grid_cache.put("a.gif", [QtGui.QPixmap(10, 10), QtGui.QPixmap(10, 10)], [100, 100])
        w.load(SimpleNamespace(render_path="a.gif"))
        w._frame_index = 1
        decoded = [QtGui.QPixmap(40, 40), QtGui.QPixmap(40, 40)]
        w._on_decoded("a.gif", decoded, [100, 100])
        assert w._frames is decoded and w._frame_index == 1
        w.stop()
        grid_cache.clear()

    def test_decoded_frames_start_over_when_the_frame_count_differs(self, qtbot):
        w, grid_cache, _ = self._widget(qtbot)
        grid_cache.put("a.gif", [QtGui.QPixmap(10, 10), QtGui.QPixmap(10, 10)], [100, 100])
        w.load(SimpleNamespace(render_path="a.gif"))
        w._frame_index = 1
        w._on_decoded("a.gif", [QtGui.QPixmap(40, 40)], [100])
        assert w._frame_index == 0
        w.stop()
        grid_cache.clear()

    def test_cached_original_is_used_instead_of_the_grid_frames(self, qtbot):
        w, grid_cache, viewer_cache = self._widget(qtbot)
        grid_cache.put("a.gif", [QtGui.QPixmap(10, 10)], [100])
        original = [QtGui.QPixmap(40, 40)]
        viewer_cache.put("a.gif", original, [100])
        w.load(SimpleNamespace(render_path="a.gif"))
        assert w._frames is original
        grid_cache.clear()
        viewer_cache.clear()


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
        from wafer.plugin import ViewerContext

        w = AnimatedViewerWidget()
        qtbot.addWidget(w)
        w._viewer_context = ViewerContext(path="/archive.zip::test.gif", source="/archive.zip", render_path="/cache/test.gif")
        ctx = w.extend_context(None, None)
        assert ctx == {
            "path": "/archive.zip::test.gif",
            "paths": ["/archive.zip::test.gif"],
            "source": "/archive.zip",
            "sources": ["/archive.zip"],
            "render_path": "/cache/test.gif",
            "render_paths": ["/cache/test.gif"],
        }

    def test_returns_empty_paths_when_no_path(self, qtbot):
        from extensions.animated.viewer_widget import AnimatedViewerWidget

        w = AnimatedViewerWidget()
        qtbot.addWidget(w)
        ctx = w.extend_context(None, None)
        assert ctx == {"path": None, "paths": [], "source": None, "sources": [], "render_path": None, "render_paths": []}
