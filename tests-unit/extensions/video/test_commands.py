import pytest
from unittest.mock import MagicMock, patch


mpv_mock = MagicMock()
mpv_mock.MpvGlGetProcAddressFn = MagicMock(return_value=MagicMock())


@pytest.fixture(autouse=True)
def _patch_mpv(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "mpv", mpv_mock)
    from extensions.video.widget import MpvGLOverlay

    monkeypatch.setattr(MpvGLOverlay, "_mpv", mpv_mock)
    monkeypatch.setattr(MpvGLOverlay, "_init_attempted", True)


@pytest.fixture(autouse=True)
def _reset_shared(monkeypatch):
    from extensions.video.widget import MpvCellWidget

    monkeypatch.setattr(MpvCellWidget, "_slot_manager", None)
    monkeypatch.setattr(MpvCellWidget, "_shared_initialized", False)
    yield


def _make_ctx(sm=None):
    ctx = MagicMock()
    ctx.get_instance = MagicMock(return_value=sm)
    return ctx


class TestToggleHoverAutoplay:
    def test_toggle_hover_off_deactivates_hover(self):
        from extensions.video.commands import toggle_hover_autoplay

        sm = MagicMock()
        sm.hover_autoplay = True
        ctx = _make_ctx(sm)
        toggle_hover_autoplay(ctx)
        sm.deactivate_hover.assert_called_once()

    def test_toggle_hover_on_does_not_deactivate(self):
        from extensions.video.commands import toggle_hover_autoplay

        sm = MagicMock()
        sm.hover_autoplay = False
        ctx = _make_ctx(sm)
        toggle_hover_autoplay(ctx)
        sm.deactivate_hover.assert_not_called()


class TestHoverAutoplayFlag:
    def test_enter_event_skipped_when_hover_disabled(self):
        from extensions.video.widget import MpvCellWidget

        cell = MagicMock(spec=MpvCellWidget)
        cell._path = "/test.mp4"
        cell._slot_manager = MagicMock()
        cell._slot_manager.hover_autoplay = False
        with patch.object(MpvCellWidget.__bases__[0], "enterEvent"):
            MpvCellWidget.enterEvent(cell, MagicMock())
        cell._slot_manager.activate_hover.assert_not_called()

    def test_enter_event_called_when_hover_enabled(self):
        from extensions.video.widget import MpvCellWidget

        cell = MagicMock(spec=MpvCellWidget)
        cell._path = "/test.mp4"
        cell._slot_manager = MagicMock()
        cell._slot_manager.hover_autoplay = True
        with patch.object(MpvCellWidget.__bases__[0], "enterEvent"):
            MpvCellWidget.enterEvent(cell, MagicMock())
        cell._slot_manager.activate_hover.assert_called_once()


class TestAppearAutoplayFlag:
    def test_on_appeared_skipped_when_appear_disabled(self):
        from extensions.video.widget import MpvCellWidget

        cell = MagicMock(spec=MpvCellWidget)
        cell._path = "/test.mp4"
        cell._slot_manager = MagicMock()
        cell._slot_manager.appear_autoplay = False
        MpvCellWidget.on_appeared(cell)
        cell._slot_manager.activate_appear.assert_not_called()


class TestSelectAutoplayFlag:
    def test_on_selected_skipped_when_select_disabled(self):
        from extensions.video.widget import MpvCellWidget

        cell = MagicMock(spec=MpvCellWidget)
        cell._path = "/test.mp4"
        cell._slot_manager = MagicMock()
        cell._slot_manager.select_autoplay = False
        MpvCellWidget.on_selected(cell)
        cell._slot_manager.activate_select.assert_not_called()


class TestTogglePauseInBackground:
    def test_toggle_pause_in_background(self):
        from extensions.video.commands import toggle_pause_in_background

        sm = MagicMock()
        sm.pause_in_background = False
        ctx = _make_ctx(sm)
        toggle_pause_in_background(ctx)
        assert sm.pause_in_background is True
        toggle_pause_in_background(ctx)
        assert sm.pause_in_background is False


class TestSlotManagerSetVolume:
    def test_set_volume_stores_and_propagates(self):
        from extensions.video.widget import PlaybackSlotManager

        sm = object.__new__(PlaybackSlotManager)
        overlay_pool = MagicMock()
        overlay_selected = MagicMock()
        sm._pool = [overlay_pool]
        sm._hover_overlay = None
        sm._selected = {MagicMock(): overlay_selected}
        sm._appeared = {}
        sm.set_volume(80)
        assert sm.volume == 80
        overlay_pool.set_volume.assert_called_once_with(80)
        overlay_selected.set_volume.assert_called_once_with(80)

    def test_set_volume_clamps(self):
        from extensions.video.widget import PlaybackSlotManager

        sm = object.__new__(PlaybackSlotManager)
        sm._pool = []
        sm._hover_overlay = None
        sm._selected = {}
        sm._appeared = {}
        sm.set_volume(200)
        assert sm.volume == 100
        sm.set_volume(-10)
        assert sm.volume == 0

    def test_set_volume_includes_hover_overlay(self):
        from extensions.video.widget import PlaybackSlotManager

        sm = object.__new__(PlaybackSlotManager)
        hover = MagicMock()
        sm._pool = []
        sm._hover_overlay = hover
        sm._selected = {}
        sm._appeared = {}
        sm.set_volume(50)
        assert sm.volume == 50
        hover.set_volume.assert_called_once_with(50)


class TestSlotManagerSetMaxSelected:
    def test_set_max_selected_evicts_excess(self):
        from collections import OrderedDict
        from extensions.video.widget import PlaybackSlotManager

        sm = object.__new__(PlaybackSlotManager)
        sm._pool = []
        sm._parent = MagicMock()
        sm._appeared = OrderedDict()
        sel = OrderedDict()
        for i in range(4):
            sel[MagicMock()] = MagicMock()
        sm._selected = sel
        sm.set_max_selected(2)
        assert len(sm._selected) == 2
        assert sm._max_selected == 2

    def test_set_max_selected_clamps_to_one(self):
        from collections import OrderedDict
        from extensions.video.widget import PlaybackSlotManager

        sm = object.__new__(PlaybackSlotManager)
        sm._pool = []
        sm._parent = MagicMock()
        sm._appeared = OrderedDict()
        sm._selected = OrderedDict()
        sm.set_max_selected(0)
        assert sm._max_selected == 1


class TestMpvGLOverlaySetVolume:
    def test_set_volume_no_player(self):
        from extensions.video.widget import MpvGLOverlay

        overlay = MagicMock(spec=MpvGLOverlay)
        overlay.player = None
        MpvGLOverlay.set_volume(overlay, 75)


@pytest.fixture()
def video_registry(monkeypatch):
    from wafer.qt.commands.command.core import CommandRegistry

    registry = CommandRegistry.instance()
    prev = dict(registry._commands)
    registry._commands = {}
    from extensions.video.commands import VideoGridCommands

    VideoGridCommands._flags = {}
    VideoGridCommands.register()
    yield registry
    registry._commands = prev


@pytest.fixture()
def mock_slot_manager():
    from wafer.qt.commands.binding.instance_registry import InstanceRegistry

    reg = InstanceRegistry.instance()
    sm = MagicMock()
    sm.hover_autoplay = True
    sm.appear_autoplay = True
    sm.select_autoplay = True
    sm.volume = 40
    reg.register("VideoSlotManager", sm)
    yield sm
    entries = reg._by_name.get("VideoSlotManager", [])
    entries.clear()


class TestRegistryExecution:
    def test_volume_up_via_registry(self, video_registry, mock_slot_manager):
        from wafer.qt.commands.command.context import CommandContext

        ctx = CommandContext.create(None, "*", source="menu")
        video_registry.execute("vgrid.volume_up", ctx=ctx, step=10)
        mock_slot_manager.set_volume.assert_called_once_with(50)

    def test_volume_down_via_registry(self, video_registry, mock_slot_manager):
        from wafer.qt.commands.command.context import CommandContext

        ctx = CommandContext.create(None, "*", source="menu")
        video_registry.execute("vgrid.volume_down", ctx=ctx, step=10)
        mock_slot_manager.set_volume.assert_called_once_with(30)

    def test_set_max_slots_via_registry(self, video_registry, mock_slot_manager):
        from wafer.qt.commands.command.context import CommandContext

        ctx = CommandContext.create(None, "*", source="menu")
        video_registry.execute("vgrid.set_max_playback_slots", ctx=ctx, max_slots=7)
        mock_slot_manager.set_max_selected.assert_called_once_with(7)

    def test_toggle_hover_via_registry(self, video_registry, mock_slot_manager):
        from wafer.qt.commands.command.context import CommandContext

        assert mock_slot_manager.hover_autoplay is True
        ctx = CommandContext.create(None, "*", source="menu")
        video_registry.execute("vgrid.toggle_hover_autoplay", ctx=ctx)
        assert mock_slot_manager.hover_autoplay is False

    def test_toggle_appear_via_registry(self, video_registry, mock_slot_manager):
        from wafer.qt.commands.command.context import CommandContext

        assert mock_slot_manager.appear_autoplay is True
        ctx = CommandContext.create(None, "*", source="menu")
        video_registry.execute("vgrid.toggle_appear_autoplay", ctx=ctx)
        assert mock_slot_manager.appear_autoplay is False

    def test_toggle_select_via_registry(self, video_registry, mock_slot_manager):
        from wafer.qt.commands.command.context import CommandContext

        assert mock_slot_manager.select_autoplay is True
        ctx = CommandContext.create(None, "*", source="menu")
        video_registry.execute("vgrid.toggle_select_autoplay", ctx=ctx)
        assert mock_slot_manager.select_autoplay is False
