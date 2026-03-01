import pytest

from afterimages.app.viewer.commands.grid_commands import (
    ORIENTATION_CHOICES,
    _CMD_IDS,
    _CMD_TO_CHOICE,
    _CHOICE_TO_CMD,
    _CHOICE_TO_INDEX,
)
from afterimages.core.actions.command.state import ActionGroupStateManager, CommandOptionStore


GROUP = "grid_orientation"


@pytest.fixture(autouse=True)
def _reset_state():
    sm = ActionGroupStateManager()
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
    store = CommandOptionStore()
    store._ensure_loaded()
    for k in list(store._map):
        if k.startswith("grid.orientation_") or k == f"__group__{GROUP}":
            del store._map[k]
    for k in list(store._buffer):
        if k.startswith("grid.orientation_") or k == f"__group__{GROUP}":
            del store._buffer[k]
    yield


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
        sm = ActionGroupStateManager()
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
        sm = ActionGroupStateManager()
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
        sm = ActionGroupStateManager()
        for cmd_id in _CMD_IDS:
            sm.register_member(GROUP, cmd_id)

        store = CommandOptionStore()
        store.set(f"__group__{GROUP}", {"selected": "grid.orientation_Z(ↁE"})

        if GROUP in sm._group_states:
            del sm._group_states[GROUP]

        result = sm.get_current(GROUP)
        assert result is None or result in _CMD_IDS

    def test_valid_stored_state_is_kept(self):
        sm = ActionGroupStateManager()
        for cmd_id in _CMD_IDS:
            sm.register_member(GROUP, cmd_id)

        store = CommandOptionStore()
        store.set(f"__group__{GROUP}", {"selected": "grid.orientation_n"})

        if GROUP in sm._group_states:
            del sm._group_states[GROUP]

        result = sm.get_current(GROUP)
        assert result == "grid.orientation_n"
