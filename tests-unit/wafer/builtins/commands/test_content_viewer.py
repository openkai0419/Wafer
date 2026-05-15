from unittest.mock import MagicMock

from PySide6 import QtCore

from wafer.builtins.commands.content_viewer import (
    _nav_direction,
    navigate_file_by_mouse_position,
    next_file,
    prev_file,
    toggle_slideshow,
    start_slideshow,
    stop_slideshow,
)


class DummyCtx:
    def __init__(self, viewer, *, widget=None, global_pos=None):
        self._viewer = viewer
        self._widget = widget
        self.global_pos = global_pos

    def get(self, key, default=None):
        return default

    def get_instance(self, name, default=None):
        if name == "FileViewerController":
            return self._viewer
        return default


def _make_viewer():
    viewer = MagicMock()
    viewer.navigate_next = MagicMock()
    viewer.navigate_prev = MagicMock()
    return viewer


class _WidgetStub:
    def __init__(self, rect, local_pos):
        self._rect = rect
        self._local_pos = local_pos

    def rect(self):
        return self._rect

    def mapFromGlobal(self, global_pos):
        return self._local_pos


def test_next_file_delegates_to_controller():
    viewer = _make_viewer()

    next_file(DummyCtx(viewer))

    viewer.navigate_next.assert_called_once_with(step=1, loop=False, origin="command")


def test_prev_file_delegates_to_controller():
    viewer = _make_viewer()

    prev_file(DummyCtx(viewer))

    viewer.navigate_prev.assert_called_once_with(step=1, loop=False, origin="command")


def test_next_prev_forward_step_and_loop_parameters():
    viewer = _make_viewer()
    ctx = DummyCtx(viewer)

    next_file(ctx, step=2, loop=True)
    prev_file(ctx, step=3, loop=True)

    viewer.navigate_next.assert_called_once_with(step=2, loop=True, origin="command")
    viewer.navigate_prev.assert_called_once_with(step=3, loop=True, origin="command")


def test_nav_direction_defaults_to_left_right_axis():
    center = QtCore.QPoint(50, 50)
    assert _nav_direction(QtCore.QPoint(90, 60), center) == "next"
    assert _nav_direction(QtCore.QPoint(10, 45), center) == "prev"
    assert _nav_direction(QtCore.QPoint(55, 95), center) == "next"
    assert _nav_direction(QtCore.QPoint(48, 5), center) == "prev"


def test_nav_direction_supports_axis_aliases_and_invert():
    center = QtCore.QPoint(50, 50)
    assert _nav_direction(QtCore.QPoint(10, 90), center, axis="left/right") == "prev"
    assert _nav_direction(QtCore.QPoint(10, 90), center, axis="up/down") == "next"
    assert _nav_direction(QtCore.QPoint(10, 90), center, axis="horizontal") == "prev"
    assert _nav_direction(QtCore.QPoint(10, 90), center, axis="vertical") == "next"
    assert _nav_direction(QtCore.QPoint(20, 90), center, axis="dominant") == "next"
    assert _nav_direction(QtCore.QPoint(90, 60), center, invert=True) == "prev"


def test_navigate_file_by_mouse_position_moves_next_and_prev():
    viewer = _make_viewer()
    right_widget = _WidgetStub(QtCore.QRect(0, 0, 100, 100), QtCore.QPoint(90, 40))
    left_widget = _WidgetStub(QtCore.QRect(0, 0, 100, 100), QtCore.QPoint(10, 40))

    navigate_file_by_mouse_position(DummyCtx(viewer, widget=right_widget, global_pos=QtCore.QPoint(0, 0)))
    viewer.navigate_next.assert_called_once_with(step=1, loop=False, origin="mouse")

    navigate_file_by_mouse_position(DummyCtx(viewer, widget=left_widget, global_pos=QtCore.QPoint(0, 0)))
    viewer.navigate_prev.assert_called_once_with(step=1, loop=False, origin="mouse")


def test_navigate_file_by_mouse_position_honors_invert():
    viewer = _make_viewer()
    widget = _WidgetStub(QtCore.QRect(0, 0, 100, 100), QtCore.QPoint(90, 40))

    navigate_file_by_mouse_position(DummyCtx(viewer, widget=widget, global_pos=QtCore.QPoint(0, 0)), invert=True)
    viewer.navigate_prev.assert_called_once_with(step=1, loop=False, origin="mouse")

    navigate_file_by_mouse_position(DummyCtx(viewer, widget=widget, global_pos=QtCore.QPoint(0, 0)))
    viewer.navigate_next.assert_called_once_with(step=1, loop=False, origin="mouse")


def test_navigate_file_by_mouse_position_honors_axis_selection():
    viewer = _make_viewer()
    widget = _WidgetStub(QtCore.QRect(0, 0, 100, 100), QtCore.QPoint(10, 90))

    navigate_file_by_mouse_position(DummyCtx(viewer, widget=widget, global_pos=QtCore.QPoint(0, 0)), axis="left/right")
    viewer.navigate_prev.assert_called_once_with(step=1, loop=False, origin="mouse")

    navigate_file_by_mouse_position(DummyCtx(viewer, widget=widget, global_pos=QtCore.QPoint(0, 0)), axis="up/down")
    viewer.navigate_next.assert_called_once_with(step=1, loop=False, origin="mouse")


def test_navigate_file_by_mouse_position_warns_without_widget(monkeypatch):
    viewer = _make_viewer()
    warnings = []

    monkeypatch.setattr("wafer.builtins.commands.content_viewer.Notifier.warning", warnings.append)

    navigate_file_by_mouse_position(DummyCtx(viewer))

    assert warnings == ["Positional navigation requires a bound widget"]
    viewer.navigate_next.assert_not_called()
    viewer.navigate_prev.assert_not_called()


class _SlideshowCtx:
    def __init__(self, fv):
        self._fv = fv

    def get(self, key, default=None):
        return default

    def get_instance(self, name, default=None):
        if name == "FileViewerController":
            return self._fv
        return default


def test_toggle_slideshow_starts_autoplay():
    fv = MagicMock()
    fv.autoplay_active = False
    ctx = _SlideshowCtx(fv)
    toggle_slideshow(ctx, interval=5.0, loop=True)
    fv.toggle_autoplay.assert_called_once_with(interval_ms=5000, loop=True)


def test_start_slideshow_calls_start():
    fv = MagicMock()
    ctx = _SlideshowCtx(fv)
    start_slideshow(ctx, interval=2.0, loop=False)
    fv.start_autoplay.assert_called_once_with(interval_ms=2000, loop=False)


def test_stop_slideshow_calls_stop():
    fv = MagicMock()
    ctx = _SlideshowCtx(fv)
    stop_slideshow(ctx)
    fv.stop_autoplay.assert_called_once()
