import pytest
from unittest.mock import MagicMock, patch


mpv_mock = MagicMock()
mpv_mock.MpvGlGetProcAddressFn = MagicMock(return_value=MagicMock())


@pytest.fixture(autouse=True)
def _patch_mpv(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, 'mpv', mpv_mock)
    from extensions.video.widget import MpvGLOverlay
    monkeypatch.setattr(MpvGLOverlay, '_mpv', mpv_mock)
    monkeypatch.setattr(MpvGLOverlay, '_init_attempted', True)


@pytest.fixture(autouse=True)
def _reset_shared(monkeypatch):
    from extensions.video import widget as w
    from extensions.video.widget import MpvCellWidget
    monkeypatch.setattr(MpvCellWidget, '_slot_manager', None)
    monkeypatch.setattr(MpvCellWidget, '_thread_pool', None)
    monkeypatch.setattr(MpvCellWidget, '_shared_initialized', False)
    monkeypatch.setattr(w, '_volume', 40)
    monkeypatch.setattr(w, '_hover_autoplay', True)
    monkeypatch.setattr(w, '_appear_autoplay', True)
    yield


class TestSetVolume:
    def test_set_volume_updates_module_state(self):
        from extensions.video import widget as w
        from extensions.video.commands import set_volume
        set_volume(MagicMock(), volume=75)
        assert w._volume == 75

    def test_set_volume_clamps_max(self):
        from extensions.video import widget as w
        from extensions.video.commands import set_volume
        set_volume(MagicMock(), volume=200)
        assert w._volume == 100

    def test_set_volume_clamps_min(self):
        from extensions.video import widget as w
        from extensions.video.commands import set_volume
        set_volume(MagicMock(), volume=-10)
        assert w._volume == 0

    def test_set_volume_propagates_to_slot_manager(self):
        from extensions.video.widget import MpvCellWidget
        from extensions.video.commands import set_volume
        mock_sm = MagicMock()
        MpvCellWidget._slot_manager = mock_sm
        set_volume(MagicMock(), volume=60)
        mock_sm.set_volume.assert_called_once_with(60)


class TestSetMaxPlaybackSlots:
    def test_set_max_playback_slots(self):
        from extensions.video.widget import MpvCellWidget, PlaybackSlotManager
        mock_sm = MagicMock(spec=PlaybackSlotManager)
        mock_sm._max_selected = 3
        mock_sm._selected = {}
        MpvCellWidget._slot_manager = mock_sm
        from extensions.video.commands import set_max_playback_slots
        set_max_playback_slots(MagicMock(), max_slots=5)
        mock_sm.set_max_selected.assert_called_once_with(5)


class TestToggleHoverAutoplay:
    def test_toggle_hover_off(self):
        from extensions.video import widget as w
        from extensions.video.commands import toggle_hover_autoplay
        assert w._hover_autoplay is True
        with patch("extensions.video.commands.Command"):
            toggle_hover_autoplay(MagicMock())
        assert w._hover_autoplay is False

    def test_toggle_hover_on(self, monkeypatch):
        from extensions.video import widget as w
        from extensions.video.commands import toggle_hover_autoplay
        monkeypatch.setattr(w, '_hover_autoplay', False)
        with patch("extensions.video.commands.Command"):
            toggle_hover_autoplay(MagicMock())
        assert w._hover_autoplay is True

    def test_toggle_hover_off_deactivates_hover(self):
        from extensions.video.widget import MpvCellWidget
        from extensions.video.commands import toggle_hover_autoplay
        mock_sm = MagicMock()
        MpvCellWidget._slot_manager = mock_sm
        with patch("extensions.video.commands.Command"):
            toggle_hover_autoplay(MagicMock())
        mock_sm.deactivate_hover.assert_called_once()

    def test_set_checked_uses_vgrid_path(self):
        from extensions.video.commands import toggle_hover_autoplay
        with patch("extensions.video.commands.Command") as cmd:
            toggle_hover_autoplay(MagicMock())
            cmd.set_checked.assert_called_once_with("vgrid.toggle_hover_autoplay", False)


class TestToggleAppearAutoplay:
    def test_toggle_appear_off(self):
        from extensions.video import widget as w
        from extensions.video.commands import toggle_appear_autoplay
        assert w._appear_autoplay is True
        with patch("extensions.video.commands.Command"):
            toggle_appear_autoplay(MagicMock())
        assert w._appear_autoplay is False

    def test_toggle_appear_on(self, monkeypatch):
        from extensions.video import widget as w
        from extensions.video.commands import toggle_appear_autoplay
        monkeypatch.setattr(w, '_appear_autoplay', False)
        with patch("extensions.video.commands.Command"):
            toggle_appear_autoplay(MagicMock())
        assert w._appear_autoplay is True


class TestHoverAutoplayFlag:
    def test_enter_event_skipped_when_hover_disabled(self, monkeypatch):
        from extensions.video import widget as w
        from extensions.video.widget import MpvCellWidget
        monkeypatch.setattr(w, '_hover_autoplay', False)
        cell = MagicMock(spec=MpvCellWidget)
        cell._path = '/test.mp4'
        cell._slot_manager = MagicMock()
        with patch.object(MpvCellWidget.__bases__[0], 'enterEvent'):
            MpvCellWidget.enterEvent(cell, MagicMock())
        cell._slot_manager.activate_hover.assert_not_called()

    def test_enter_event_called_when_hover_enabled(self):
        from extensions.video.widget import MpvCellWidget
        cell = MagicMock(spec=MpvCellWidget)
        cell._path = '/test.mp4'
        cell._slot_manager = MagicMock()
        with patch.object(MpvCellWidget.__bases__[0], 'enterEvent'):
            MpvCellWidget.enterEvent(cell, MagicMock())
        cell._slot_manager.activate_hover.assert_called_once()


class TestAppearAutoplayFlag:
    def test_on_selected_skipped_when_appear_disabled(self, monkeypatch):
        from extensions.video import widget as w
        from extensions.video.widget import MpvCellWidget
        monkeypatch.setattr(w, '_appear_autoplay', False)
        cell = MagicMock(spec=MpvCellWidget)
        cell._path = '/test.mp4'
        cell._slot_manager = MagicMock()
        MpvCellWidget.on_selected(cell)
        cell._slot_manager.activate_select.assert_not_called()

    def test_on_selected_called_when_appear_enabled(self):
        from extensions.video.widget import MpvCellWidget
        cell = MagicMock(spec=MpvCellWidget)
        cell._path = '/test.mp4'
        cell._slot_manager = MagicMock()
        MpvCellWidget.on_selected(cell)
        cell._slot_manager.activate_select.assert_called_once()


class TestSlotManagerSetVolume:
    def test_set_volume_propagates_to_all_overlays(self):
        from extensions.video.widget import PlaybackSlotManager
        sm = object.__new__(PlaybackSlotManager)
        overlay_pool = MagicMock()
        overlay_selected = MagicMock()
        sm._pool = [overlay_pool]
        sm._hover_overlay = None
        sm._selected = {MagicMock(): overlay_selected}
        sm.set_volume(80)
        overlay_pool.set_volume.assert_called_once_with(80)
        overlay_selected.set_volume.assert_called_once_with(80)

    def test_set_volume_includes_hover_overlay(self):
        from extensions.video.widget import PlaybackSlotManager
        sm = object.__new__(PlaybackSlotManager)
        hover = MagicMock()
        sm._pool = []
        sm._hover_overlay = hover
        sm._selected = {}
        sm.set_volume(50)
        hover.set_volume.assert_called_once_with(50)


class TestSlotManagerSetMaxSelected:
    def test_set_max_selected_evicts_excess(self):
        from collections import OrderedDict
        from extensions.video.widget import PlaybackSlotManager
        sm = object.__new__(PlaybackSlotManager)
        sm._pool = []
        sm._parent = MagicMock()
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
        from wayfer.core.actions.command.core import CommandMeta
        cmds = VideoGridCommands.commands()
        paths = [c.path for c in cmds if isinstance(c, CommandMeta)]
        assert "vgrid.set_volume" in paths
        assert "vgrid.set_max_playback_slots" in paths
        assert "vgrid.toggle_hover_autoplay" in paths
        assert "vgrid.toggle_appear_autoplay" in paths


@pytest.fixture()
def video_registry(monkeypatch):
    from wayfer.core.actions.command.core import CommandRegistry
    registry = CommandRegistry.instance()
    prev = dict(registry._commands)
    registry._commands = {}
    from extensions.video.commands import VideoGridCommands
    VideoGridCommands._flags = {}
    VideoGridCommands.register()
    yield registry
    registry._commands = prev


class TestRegistryExecution:
    def test_set_volume_via_registry(self, video_registry):
        from extensions.video import widget as w
        from wayfer.core.actions.command.context import CommandContext
        ctx = CommandContext.create(None, "*", source="menu")
        video_registry.execute("vgrid.set_volume", ctx=ctx, volume=75)
        assert w._volume == 75

    def test_set_volume_default_via_registry(self, video_registry):
        from extensions.video import widget as w
        from wayfer.core.actions.command.context import CommandContext
        w._volume = 80
        ctx = CommandContext.create(None, "*", source="menu")
        video_registry.execute("vgrid.set_volume", ctx=ctx)
        assert w._volume == 40

    def test_set_max_slots_via_registry(self, video_registry):
        from extensions.video.widget import MpvCellWidget
        from wayfer.core.actions.command.context import CommandContext
        mock_sm = MagicMock()
        MpvCellWidget._slot_manager = mock_sm
        ctx = CommandContext.create(None, "*", source="menu")
        video_registry.execute("vgrid.set_max_playback_slots", ctx=ctx, max_slots=7)
        mock_sm.set_max_selected.assert_called_once_with(7)

    def test_toggle_hover_via_registry(self, video_registry):
        from extensions.video import widget as w
        from wayfer.core.actions.command.context import CommandContext
        assert w._hover_autoplay is True
        ctx = CommandContext.create(None, "*", source="menu")
        with patch("extensions.video.commands.Command"):
            video_registry.execute("vgrid.toggle_hover_autoplay", ctx=ctx)
        assert w._hover_autoplay is False

    def test_toggle_appear_via_registry(self, video_registry):
        from extensions.video import widget as w
        from wayfer.core.actions.command.context import CommandContext
        assert w._appear_autoplay is True
        ctx = CommandContext.create(None, "*", source="menu")
        with patch("extensions.video.commands.Command"):
            video_registry.execute("vgrid.toggle_appear_autoplay", ctx=ctx)
        assert w._appear_autoplay is False

    def test_registered_command_ids(self, video_registry):
        assert video_registry.has_command("vgrid.set_volume")
        assert video_registry.has_command("vgrid.set_max_playback_slots")
        assert video_registry.has_command("vgrid.toggle_hover_autoplay")
        assert video_registry.has_command("vgrid.toggle_appear_autoplay")
