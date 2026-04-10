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


@pytest.fixture(autouse=True)
def _suppress_notifier(monkeypatch):
    monkeypatch.setattr(
        "wafer.core.commands.command.require.Notifier",
        type("FakeNotifier", (), {"warning": staticmethod(lambda msg: None)}),
    )


def _make_ctx(sm=None):
    ctx = MagicMock()
    ctx.get_instance = MagicMock(return_value=sm)
    return ctx


class TestVolumeUp:
    def test_volume_up_calls_slot_manager(self):
        from extensions.video.commands import volume_up

        sm = MagicMock()
        sm.volume = 40
        ctx = _make_ctx(sm)
        volume_up(ctx, step=5)
        sm.set_volume.assert_called_once_with(45)

    def test_volume_up_noop_without_instance(self):
        from extensions.video.commands import volume_up

        ctx = _make_ctx(None)
        volume_up(ctx, step=5)

    def test_volume_up_uses_ctx_get_instance(self):
        from extensions.video.commands import volume_up

        sm = MagicMock()
        sm.volume = 40
        ctx = _make_ctx(sm)
        volume_up(ctx, step=5)
        ctx.get_instance.assert_called_once_with("VideoSlotManager")


class TestVolumeDown:
    def test_volume_down_calls_slot_manager(self):
        from extensions.video.commands import volume_down

        sm = MagicMock()
        sm.volume = 40
        ctx = _make_ctx(sm)
        volume_down(ctx, step=5)
        sm.set_volume.assert_called_once_with(35)

    def test_volume_down_noop_without_instance(self):
        from extensions.video.commands import volume_down

        ctx = _make_ctx(None)
        volume_down(ctx, step=5)


class TestSetMaxPlaybackSlots:
    def test_set_max_playback_slots(self):
        from extensions.video.commands import set_max_playback_slots

        sm = MagicMock()
        ctx = _make_ctx(sm)
        set_max_playback_slots(ctx, max_slots=5)
        sm.set_max_selected.assert_called_once_with(5)

    def test_set_max_playback_slots_noop_without_instance(self):
        from extensions.video.commands import set_max_playback_slots

        ctx = _make_ctx(None)
        set_max_playback_slots(ctx, max_slots=5)


class TestToggleHoverAutoplay:
    def test_toggle_hover_off(self):
        from extensions.video.commands import toggle_hover_autoplay

        sm = MagicMock()
        sm.hover_autoplay = True
        ctx = _make_ctx(sm)
        toggle_hover_autoplay(ctx)
        assert sm.hover_autoplay is False

    def test_toggle_hover_on(self):
        from extensions.video.commands import toggle_hover_autoplay

        sm = MagicMock()
        sm.hover_autoplay = False
        ctx = _make_ctx(sm)
        toggle_hover_autoplay(ctx)
        assert sm.hover_autoplay is True

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

    def test_noop_without_instance(self):
        from extensions.video.commands import toggle_hover_autoplay

        ctx = _make_ctx(None)
        toggle_hover_autoplay(ctx)


class TestToggleAppearAutoplay:
    def test_toggle_appear_off(self):
        from extensions.video.commands import toggle_appear_autoplay

        sm = MagicMock()
        sm.appear_autoplay = True
        ctx = _make_ctx(sm)
        toggle_appear_autoplay(ctx)
        assert sm.appear_autoplay is False

    def test_toggle_appear_on(self):
        from extensions.video.commands import toggle_appear_autoplay

        sm = MagicMock()
        sm.appear_autoplay = False
        ctx = _make_ctx(sm)
        toggle_appear_autoplay(ctx)
        assert sm.appear_autoplay is True

    def test_noop_without_instance(self):
        from extensions.video.commands import toggle_appear_autoplay

        ctx = _make_ctx(None)
        toggle_appear_autoplay(ctx)


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

    def test_on_appeared_called_when_appear_enabled(self):
        from extensions.video.widget import MpvCellWidget

        cell = MagicMock(spec=MpvCellWidget)
        cell._path = "/test.mp4"
        cell._slot_manager = MagicMock()
        cell._slot_manager.appear_autoplay = True
        MpvCellWidget.on_appeared(cell)
        cell._slot_manager.activate_appear.assert_called_once()


class TestToggleSelectAutoplay:
    def test_toggle_select_off(self):
        from extensions.video.commands import toggle_select_autoplay

        sm = MagicMock()
        sm.select_autoplay = True
        ctx = _make_ctx(sm)
        toggle_select_autoplay(ctx)
        assert sm.select_autoplay is False

    def test_toggle_select_on(self):
        from extensions.video.commands import toggle_select_autoplay

        sm = MagicMock()
        sm.select_autoplay = False
        ctx = _make_ctx(sm)
        toggle_select_autoplay(ctx)
        assert sm.select_autoplay is True

    def test_noop_without_instance(self):
        from extensions.video.commands import toggle_select_autoplay

        ctx = _make_ctx(None)
        toggle_select_autoplay(ctx)


class TestSelectAutoplayFlag:
    def test_on_selected_skipped_when_select_disabled(self):
        from extensions.video.widget import MpvCellWidget

        cell = MagicMock(spec=MpvCellWidget)
        cell._path = "/test.mp4"
        cell._slot_manager = MagicMock()
        cell._slot_manager.select_autoplay = False
        MpvCellWidget.on_selected(cell)
        cell._slot_manager.activate_select.assert_not_called()

    def test_on_selected_called_when_select_enabled(self):
        from extensions.video.widget import MpvCellWidget

        cell = MagicMock(spec=MpvCellWidget)
        cell._path = "/test.mp4"
        cell._slot_manager = MagicMock()
        cell._slot_manager.select_autoplay = True
        MpvCellWidget.on_selected(cell)
        cell._slot_manager.activate_select.assert_called_once()


class TestTogglePauseInBackground:
    def test_toggle_pause_in_background_on(self):
        from extensions.video.commands import toggle_pause_in_background

        sm = MagicMock()
        sm.pause_in_background = False
        ctx = _make_ctx(sm)
        toggle_pause_in_background(ctx)
        assert sm.pause_in_background is True

    def test_toggle_pause_in_background_off(self):
        from extensions.video.commands import toggle_pause_in_background

        sm = MagicMock()
        sm.pause_in_background = True
        ctx = _make_ctx(sm)
        toggle_pause_in_background(ctx)
        assert sm.pause_in_background is False

    def test_noop_without_instance(self):
        from extensions.video.commands import toggle_pause_in_background

        ctx = _make_ctx(None)
        toggle_pause_in_background(ctx)


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

    def test_set_volume_clamps_max(self):
        from extensions.video.widget import PlaybackSlotManager

        sm = object.__new__(PlaybackSlotManager)
        sm._pool = []
        sm._hover_overlay = None
        sm._selected = {}
        sm._appeared = {}
        sm.set_volume(200)
        assert sm.volume == 100

    def test_set_volume_clamps_min(self):
        from extensions.video.widget import PlaybackSlotManager

        sm = object.__new__(PlaybackSlotManager)
        sm._pool = []
        sm._hover_overlay = None
        sm._selected = {}
        sm._appeared = {}
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
    def test_set_volume_updates_player(self):
        from extensions.video.widget import MpvGLOverlay

        overlay = MagicMock(spec=MpvGLOverlay)
        overlay.player = MagicMock()
        MpvGLOverlay.set_volume(overlay, 75)
        assert overlay.player.volume == 75

    def test_set_volume_no_player(self):
        from extensions.video.widget import MpvGLOverlay

        overlay = MagicMock(spec=MpvGLOverlay)
        overlay.player = None
        MpvGLOverlay.set_volume(overlay, 75)


class TestVideoGridCommandsMenuGroup:
    def test_commands_returns_list(self):
        from extensions.video.commands import VideoGridCommands

        cmds = VideoGridCommands.commands()
        assert isinstance(cmds, list)
        assert len(cmds) > 0

    def test_commands_contains_expected_paths(self):
        from extensions.video.commands import VideoGridCommands
        from wafer.core.commands.command.core import CommandMeta

        cmds = VideoGridCommands.commands()
        paths = [c.path for c in cmds if isinstance(c, CommandMeta)]
        assert "vgrid.volume_up" in paths
        assert "vgrid.volume_down" in paths
        assert "vgrid.set_max_playback_slots" in paths
        assert "vgrid.toggle_hover_autoplay" in paths
        assert "vgrid.toggle_appear_autoplay" in paths
        assert "vgrid.toggle_select_autoplay" in paths


@pytest.fixture()
def video_registry(monkeypatch):
    from wafer.core.commands.command.core import CommandRegistry

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
    from wafer.core.commands.binding.instance_registry import InstanceRegistry

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
        from wafer.core.commands.command.context import CommandContext

        ctx = CommandContext.create(None, "*", source="menu")
        video_registry.execute("vgrid.volume_up", ctx=ctx, step=10)
        mock_slot_manager.set_volume.assert_called_once_with(50)

    def test_volume_down_via_registry(self, video_registry, mock_slot_manager):
        from wafer.core.commands.command.context import CommandContext

        ctx = CommandContext.create(None, "*", source="menu")
        video_registry.execute("vgrid.volume_down", ctx=ctx, step=10)
        mock_slot_manager.set_volume.assert_called_once_with(30)

    def test_set_max_slots_via_registry(self, video_registry, mock_slot_manager):
        from wafer.core.commands.command.context import CommandContext

        ctx = CommandContext.create(None, "*", source="menu")
        video_registry.execute("vgrid.set_max_playback_slots", ctx=ctx, max_slots=7)
        mock_slot_manager.set_max_selected.assert_called_once_with(7)

    def test_toggle_hover_via_registry(self, video_registry, mock_slot_manager):
        from wafer.core.commands.command.context import CommandContext

        assert mock_slot_manager.hover_autoplay is True
        ctx = CommandContext.create(None, "*", source="menu")
        video_registry.execute("vgrid.toggle_hover_autoplay", ctx=ctx)
        assert mock_slot_manager.hover_autoplay is False

    def test_toggle_appear_via_registry(self, video_registry, mock_slot_manager):
        from wafer.core.commands.command.context import CommandContext

        assert mock_slot_manager.appear_autoplay is True
        ctx = CommandContext.create(None, "*", source="menu")
        video_registry.execute("vgrid.toggle_appear_autoplay", ctx=ctx)
        assert mock_slot_manager.appear_autoplay is False

    def test_toggle_select_via_registry(self, video_registry, mock_slot_manager):
        from wafer.core.commands.command.context import CommandContext

        assert mock_slot_manager.select_autoplay is True
        ctx = CommandContext.create(None, "*", source="menu")
        video_registry.execute("vgrid.toggle_select_autoplay", ctx=ctx)
        assert mock_slot_manager.select_autoplay is False

    def test_registered_command_ids(self, video_registry):
        assert video_registry.has_command("vgrid.volume_up")
        assert video_registry.has_command("vgrid.volume_down")
        assert video_registry.has_command("vgrid.set_max_playback_slots")
        assert video_registry.has_command("vgrid.toggle_hover_autoplay")
        assert video_registry.has_command("vgrid.toggle_appear_autoplay")
        assert video_registry.has_command("vgrid.toggle_select_autoplay")
