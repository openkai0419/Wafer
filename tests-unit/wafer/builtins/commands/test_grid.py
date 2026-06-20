from wafer.builtins.commands.grid import (
    ORIENTATION_CHOICES,
    _CMD_IDS,
    _CMD_TO_CHOICE,
    _CHOICE_TO_CMD,
    _CHOICE_TO_INDEX,
)


class TestOrientationMappings:
    def test_cmd_to_choice_keys_match_cmd_ids(self):
        assert list(_CMD_TO_CHOICE.keys()) == _CMD_IDS

    def test_choice_to_cmd_keys_match_choices(self):
        assert list(_CHOICE_TO_CMD.keys()) == ORIENTATION_CHOICES

    def test_roundtrip_cmd_to_choice_to_cmd(self):
        for cmd_id in _CMD_IDS:
            assert _CHOICE_TO_CMD[_CMD_TO_CHOICE[cmd_id]] == cmd_id

    def test_roundtrip_choice_to_cmd_to_choice(self):
        for choice in ORIENTATION_CHOICES:
            assert _CMD_TO_CHOICE[_CHOICE_TO_CMD[choice]] == choice

    def test_choice_to_index_covers_all(self):
        for i, c in enumerate(ORIENTATION_CHOICES):
            assert _CHOICE_TO_INDEX[c] == i

    def test_cmd_ids_count(self):
        assert len(_CMD_IDS) == len(ORIENTATION_CHOICES)


class TestToggleAutoscrollCommand:
    def test_command_has_speed_param(self):
        from wafer.builtins.commands.grid import GridViewCommands

        cmds = GridViewCommands.commands()
        autoscroll_cmd = None
        for c in cmds:
            if hasattr(c, "path") and c.path == "grid.toggle_autoscroll":
                autoscroll_cmd = c
                break
        assert autoscroll_cmd is not None
        param_names = [p.name for p in autoscroll_cmd.params]
        assert "speed" in param_names

    def test_speed_param_has_range(self):
        from wafer.builtins.commands.grid import GridViewCommands

        cmds = GridViewCommands.commands()
        for c in cmds:
            if hasattr(c, "path") and c.path == "grid.toggle_autoscroll":
                speed_param = [p for p in c.params if p.name == "speed"][0]
                assert speed_param.min_value == 1
                assert speed_param.max_value == 500
                assert speed_param.default == 50
                break

    def test_toggle_autoscroll_passes_speed(self):
        from unittest.mock import MagicMock, PropertyMock
        from wafer.builtins.commands.grid import GridViewCommands

        ctx = MagicMock()
        view = MagicMock()
        scroll = MagicMock()
        scroll.is_scrolling.return_value = False
        view.get_adjusted_scroll_speed.return_value = 42.0
        type(view).parent_scroll = PropertyMock(return_value=scroll)
        ctx.get_instance.return_value = view

        GridViewCommands.toggle_autoscroll(ctx, speed=100)

        view.get_adjusted_scroll_speed.assert_called_once_with(100)
        scroll.start_auto_scroll.assert_called_once_with(42.0, 100)

    def test_toggle_autoscroll_stops_when_scrolling(self):
        from unittest.mock import MagicMock, PropertyMock
        from wafer.builtins.commands.grid import GridViewCommands

        ctx = MagicMock()
        view = MagicMock()
        scroll = MagicMock()
        scroll.is_scrolling.return_value = True
        type(view).parent_scroll = PropertyMock(return_value=scroll)
        ctx.get_instance.return_value = view

        GridViewCommands.toggle_autoscroll(ctx, speed=100)

        scroll.stop_auto_scroll.assert_called_once()
        scroll.start_auto_scroll.assert_not_called()


class TestRadioCommandsHaveResolvers:
    def test_orientation_commands_have_resolver(self):
        from wafer.builtins.commands.grid import GridViewCommands

        cmds = GridViewCommands.commands()
        ori_cmds = [c for c in cmds if hasattr(c, "path") and "grid.orientation_" in c.path]
        assert len(ori_cmds) == len(_CMD_IDS)
        for c in ori_cmds:
            assert c.checked is not None
            assert c.action_group == "grid_orientation"

    def test_layout_commands_have_resolver(self):
        from wafer.builtins.commands.grid import GridViewCommands

        cmds = GridViewCommands.commands()
        layout_cmds = [c for c in cmds if hasattr(c, "path") and "grid.layout_" in c.path]
        assert len(layout_cmds) >= 2
        for c in layout_cmds:
            assert c.checked is not None
            assert c.action_group == "grid_layout_mode"

    def test_scroll_anchor_commands_have_resolver(self):
        from wafer.builtins.commands.grid import GridViewCommands

        cmds = GridViewCommands.commands()
        anchor_cmds = [c for c in cmds if hasattr(c, "path") and "scroll_anchor_" in c.path]
        assert len(anchor_cmds) == 2
        for c in anchor_cmds:
            assert c.checked is not None
            assert c.action_group == "grid_scroll_anchor"


class TestFollowSelectionCommand:
    def _cmd(self):
        from wafer.builtins.commands.grid import GridViewCommands

        for c in GridViewCommands.commands():
            if getattr(c, "path", None) == "grid.toggle_scroll_follow_selection":
                return c
        return None

    def test_command_registered_checkable_with_resolver(self):
        cmd = self._cmd()
        assert cmd is not None
        assert cmd.checkable is True
        assert cmd.checked is not None

    def test_toggle_flips_view_flag(self):
        from unittest.mock import MagicMock
        from wafer.builtins.commands.grid import GridViewCommands

        ctx = MagicMock()
        view = MagicMock()
        view.follow_selection_on_update = False
        ctx.get_instance.return_value = view

        GridViewCommands.toggle_scroll_follow_selection(ctx)

        view.set_follow_selection_on_update.assert_called_once_with(True)
