import pytest

from wafer.app.viewer.commands.grid_commands import (
    ORIENTATION_CHOICES,
    _CMD_IDS,
    _CMD_TO_CHOICE,
    _CHOICE_TO_CMD,
    _CHOICE_TO_INDEX,
    sync_grid_groups_from_settings,
)
from wafer.core.actions.command.state import ActionGroupStateManager, CommandOptionStore


GROUP = "grid_orientation"


@pytest.fixture(autouse=True)
def _reset_state(tmp_path):
    prev_instance = CommandOptionStore._instance
    prev_default = CommandOptionStore._default_path
    CommandOptionStore._instance = None
    CommandOptionStore._default_path = None
    CommandOptionStore.configure(tmp_path / "command_options.json")
    sm = ActionGroupStateManager.instance()
    if GROUP in sm._group_states:
        del sm._group_states[GROUP]
    for k in list(sm._check_states):
        if k.startswith("grid.orientation_"):
            del sm._check_states[k]
    if GROUP in sm._group_members:
        del sm._group_members[GROUP]
    for k in list(sm._command_to_group):
        if k.startswith("grid.orientation_"):
            del sm._command_to_group[k]
    store = CommandOptionStore.instance()
    store._ensure_loaded()
    for k in list(store._map):
        if k.startswith("grid.orientation_") or k == f"__group__{GROUP}":
            del store._map[k]
    for k in list(store._buffer):
        if k.startswith("grid.orientation_") or k == f"__group__{GROUP}":
            del store._buffer[k]
    yield
    CommandOptionStore._instance = prev_instance
    CommandOptionStore._default_path = prev_default


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


class TestCycleOrientationMapping:
    def test_all_cmd_ids_resolve_to_valid_choice(self):
        for cmd_id in _CMD_IDS:
            choice = _CMD_TO_CHOICE.get(cmd_id)
            assert choice is not None, f"{cmd_id} has no mapping"
            assert choice in ORIENTATION_CHOICES

    def test_all_choices_resolve_to_valid_cmd(self):
        for choice in ORIENTATION_CHOICES:
            cmd_id = _CHOICE_TO_CMD.get(choice)
            assert cmd_id is not None, f"{choice} has no mapping"
            assert cmd_id in _CMD_IDS

    def test_cycle_forward_sequence(self):
        sm = ActionGroupStateManager.instance()
        for cmd_id in _CMD_IDS:
            sm.register_member(GROUP, cmd_id)
        sm.set_current(GROUP, _CMD_IDS[0], save=False)

        for expected_idx in range(1, len(_CMD_IDS) + 1):
            current = sm.get_current(GROUP)
            current_key = _CMD_TO_CHOICE.get(current)
            enabled = list(ORIENTATION_CHOICES)
            idx = enabled.index(current_key)
            next_key = enabled[(idx + 1) % len(enabled)]
            cmd_id = _CHOICE_TO_CMD[next_key]
            sm.set_current(GROUP, cmd_id, save=False)
            assert sm.get_current(GROUP) == _CMD_IDS[expected_idx % len(_CMD_IDS)]

    def test_cycle_reverse_sequence(self):
        sm = ActionGroupStateManager.instance()
        for cmd_id in _CMD_IDS:
            sm.register_member(GROUP, cmd_id)
        sm.set_current(GROUP, _CMD_IDS[0], save=False)

        current = sm.get_current(GROUP)
        current_key = _CMD_TO_CHOICE.get(current)
        enabled = list(ORIENTATION_CHOICES)
        idx = enabled.index(current_key)
        next_key = enabled[(idx - 1) % len(enabled)]
        cmd_id = _CHOICE_TO_CMD[next_key]
        sm.set_current(GROUP, cmd_id, save=False)
        assert sm.get_current(GROUP) == _CMD_IDS[-1]


class TestLoadStateValidation:
    def test_invalid_stored_state_is_ignored(self):
        sm = ActionGroupStateManager.instance()
        for cmd_id in _CMD_IDS:
            sm.register_member(GROUP, cmd_id)

        store = CommandOptionStore.instance()
        store.set(f"__group__{GROUP}", {"selected": "grid.orientation_Z(ↁE"})

        if GROUP in sm._group_states:
            del sm._group_states[GROUP]

        result = sm.get_current(GROUP)
        assert result is None or result in _CMD_IDS

    def test_valid_stored_state_is_kept(self):
        sm = ActionGroupStateManager.instance()
        for cmd_id in _CMD_IDS:
            sm.register_member(GROUP, cmd_id)

        store = CommandOptionStore.instance()
        store.set(f"__group__{GROUP}", {"selected": "grid.orientation_n"})

        if GROUP in sm._group_states:
            del sm._group_states[GROUP]

        result = sm.get_current(GROUP)
        assert result == "grid.orientation_n"


class TestToggleAutoscrollCommand:
    def test_command_has_speed_param(self):
        from wafer.app.viewer.commands.grid_commands import GridViewCommands
        cmds = GridViewCommands.commands()
        autoscroll_cmd = None
        for c in cmds:
            if hasattr(c, 'path') and c.path == 'grid.toggle_autoscroll':
                autoscroll_cmd = c
                break
        assert autoscroll_cmd is not None
        param_names = [p.name for p in autoscroll_cmd.params]
        assert "speed" in param_names

    def test_speed_param_has_range(self):
        from wafer.app.viewer.commands.grid_commands import GridViewCommands
        cmds = GridViewCommands.commands()
        for c in cmds:
            if hasattr(c, 'path') and c.path == 'grid.toggle_autoscroll':
                speed_param = [p for p in c.params if p.name == "speed"][0]
                assert speed_param.min_value == 1
                assert speed_param.max_value == 500
                assert speed_param.default == 50
                break

    def test_toggle_autoscroll_passes_speed(self):
        from unittest.mock import MagicMock, PropertyMock
        from wafer.app.viewer.commands.grid_commands import GridViewCommands

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
        from wafer.app.viewer.commands.grid_commands import GridViewCommands

        ctx = MagicMock()
        view = MagicMock()
        scroll = MagicMock()
        scroll.is_scrolling.return_value = True
        type(view).parent_scroll = PropertyMock(return_value=scroll)
        ctx.get_instance.return_value = view

        GridViewCommands.toggle_autoscroll(ctx, speed=100)

        scroll.stop_auto_scroll.assert_called_once()
        scroll.start_auto_scroll.assert_not_called()


ORI_GROUP = "grid_orientation"
MODE_GROUP = "grid_layout_mode"


def _register_grid_groups():
    sm = ActionGroupStateManager.instance()
    for cmd_id in _CMD_IDS:
        sm.register_member(ORI_GROUP, cmd_id)
    sm.register_member(MODE_GROUP, "grid.layout_justified")
    sm.register_member(MODE_GROUP, "grid.layout_masonry")


class TestSyncGridGroupsFromSettings:

    def test_sync_orientation(self):
        _register_grid_groups()
        sync_grid_groups_from_settings({'orientation': 2})
        sm = ActionGroupStateManager.instance()
        assert sm.get_current(ORI_GROUP) == 'grid.orientation_n'

    def test_sync_layout_mode(self):
        _register_grid_groups()
        sync_grid_groups_from_settings({'layout_mode': 'masonry'})
        sm = ActionGroupStateManager.instance()
        assert sm.get_current(MODE_GROUP) == 'grid.layout_masonry'

    def test_sync_both(self):
        _register_grid_groups()
        sync_grid_groups_from_settings({'orientation': 1, 'layout_mode': 'justified'})
        sm = ActionGroupStateManager.instance()
        assert sm.get_current(ORI_GROUP) == 'grid.orientation_reverse_z'
        assert sm.get_current(MODE_GROUP) == 'grid.layout_justified'

    def test_sync_does_not_persist(self):
        _register_grid_groups()
        store = CommandOptionStore.instance()
        store._ensure_loaded()
        store._map.pop(f"__group__{ORI_GROUP}", None)
        store._buffer.clear()

        sync_grid_groups_from_settings({'orientation': 3})
        sm = ActionGroupStateManager.instance()
        assert sm.get_current(ORI_GROUP) == 'grid.orientation_reverse_n'

        assert f"__group__{ORI_GROUP}" not in store._buffer
        assert f"__group__{ORI_GROUP}" not in store._map

    def test_empty_settings_no_crash(self):
        _register_grid_groups()
        sync_grid_groups_from_settings({})

    def test_invalid_orientation_ignored(self):
        _register_grid_groups()
        sm = ActionGroupStateManager.instance()
        sm.set_current(ORI_GROUP, 'grid.orientation_z', save=False)
        sync_grid_groups_from_settings({'orientation': 99})
        assert sm.get_current(ORI_GROUP) == 'grid.orientation_z'

    def test_invalid_layout_mode_ignored(self):
        _register_grid_groups()
        sm = ActionGroupStateManager.instance()
        sm.set_current(MODE_GROUP, 'grid.layout_justified', save=False)
        sync_grid_groups_from_settings({'layout_mode': 'nonexistent'})
        assert sm.get_current(MODE_GROUP) == 'grid.layout_justified'


class TestGridCommandsSavePolicy:

    def test_orientation_commands_do_not_persist(self):
        _register_grid_groups()
        store = CommandOptionStore.instance()
        store._ensure_loaded()
        store._map.pop(f"__group__{ORI_GROUP}", None)
        store._buffer.clear()

        sm = ActionGroupStateManager.instance()
        sm.set_current(ORI_GROUP, 'grid.orientation_n', save=False)

        assert f"__group__{ORI_GROUP}" not in store._buffer

    def test_layout_mode_commands_do_not_persist(self):
        _register_grid_groups()
        store = CommandOptionStore.instance()
        store._ensure_loaded()
        store._map.pop(f"__group__{MODE_GROUP}", None)
        store._buffer.clear()

        sm = ActionGroupStateManager.instance()
        sm.set_current(MODE_GROUP, 'grid.layout_masonry', save=False)

        assert f"__group__{MODE_GROUP}" not in store._buffer
