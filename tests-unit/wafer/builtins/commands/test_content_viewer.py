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
from wafer.app.viewer.preview.file_model import FileViewModel


class DummyCtx:
    def __init__(self, model, *, widget=None, global_pos=None):
        self._model = model
        self._widget = widget
        self.global_pos = global_pos

    def get(self, key, default=None):
        return default

    def get_instance(self, name, default=None):
        if name == "FileViewModel":
            return self._model
        return default


def _make_ctx(paths):
    model = FileViewModel()
    model.set_items(paths, None)
    return DummyCtx(model), model


class _WidgetStub:
    def __init__(self, rect, local_pos):
        self._rect = rect
        self._local_pos = local_pos

    def rect(self):
        return self._rect

    def mapFromGlobal(self, global_pos):
        return self._local_pos


def test_file_viewer_next_prev_switches_path():
    ctx, model = _make_ctx(["a", "b", "c"])

    next_file(ctx)
    assert model.path() == "b"
    assert model.current_index() == 1

    next_file(ctx)
    assert model.path() == "c"
    assert model.current_index() == 2

    prev_file(ctx)
    assert model.path() == "b"
    assert model.current_index() == 1


def test_file_viewer_wrap_option():
    ctx, model = _make_ctx(["a", "b", "c"])

    next_file(ctx)
    next_file(ctx)
    next_file(ctx)
    assert model.path() == "c"

    next_file(ctx, loop=True)
    assert model.path() == "a"

    prev_file(ctx, loop=True)
    assert model.path() == "c"


def test_file_viewer_empty_model_does_nothing():
    ctx, model = _make_ctx([])
    next_file(ctx)
    assert model.path() is None
    prev_file(ctx)
    assert model.path() is None


def test_file_viewer_step():
    ctx, model = _make_ctx(["a", "b", "c", "d", "e"])

    next_file(ctx)
    assert model.current_index() == 1

    next_file(ctx, step=2)
    assert model.current_index() == 3

    next_file(ctx, step=2)
    assert model.current_index() == 4

    prev_file(ctx, step=3)
    assert model.current_index() == 1


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
    model = FileViewModel()
    model.set_items(["a", "b", "c"], None)
    right_widget = _WidgetStub(QtCore.QRect(0, 0, 100, 100), QtCore.QPoint(90, 40))
    left_widget = _WidgetStub(QtCore.QRect(0, 0, 100, 100), QtCore.QPoint(10, 40))

    navigate_file_by_mouse_position(DummyCtx(model, widget=right_widget, global_pos=QtCore.QPoint(0, 0)))
    assert model.current_index() == 1

    navigate_file_by_mouse_position(DummyCtx(model, widget=left_widget, global_pos=QtCore.QPoint(0, 0)))
    assert model.current_index() == 0


def test_navigate_file_by_mouse_position_honors_invert():
    model = FileViewModel()
    model.set_items(["a", "b", "c", "d", "e"], None)
    widget = _WidgetStub(QtCore.QRect(0, 0, 100, 100), QtCore.QPoint(90, 40))

    navigate_file_by_mouse_position(DummyCtx(model, widget=widget, global_pos=QtCore.QPoint(0, 0)), invert=True)
    assert model.current_index() == 0

    navigate_file_by_mouse_position(DummyCtx(model, widget=widget, global_pos=QtCore.QPoint(0, 0)))
    assert model.current_index() == 1


def test_navigate_file_by_mouse_position_honors_axis_selection():
    model = FileViewModel()
    model.set_items(["a", "b", "c"], None)
    widget = _WidgetStub(QtCore.QRect(0, 0, 100, 100), QtCore.QPoint(10, 90))

    navigate_file_by_mouse_position(DummyCtx(model, widget=widget, global_pos=QtCore.QPoint(0, 0)), axis="left/right")
    assert model.current_index() == 0

    navigate_file_by_mouse_position(DummyCtx(model, widget=widget, global_pos=QtCore.QPoint(0, 0)), axis="up/down")
    assert model.current_index() == 1


def test_navigate_file_by_mouse_position_warns_without_widget(monkeypatch):
    model = FileViewModel()
    model.set_items(["a", "b"], None)
    warnings = []

    monkeypatch.setattr("wafer.builtins.commands.content_viewer.Notifier.warning", warnings.append)

    navigate_file_by_mouse_position(DummyCtx(model))

    assert warnings == ["Positional navigation requires a bound widget"]
    assert model.current_index() is None


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
