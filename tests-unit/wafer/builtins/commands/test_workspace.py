from unittest.mock import MagicMock, patch

import pytest

from wafer.builtins.commands import workspace as workspace_commands
from wafer.core.workspace import BarSpec, QueryPreset, UIPreset, WindowSlot


class _Ctx:
    def __init__(self, window=None, **instances):
        self._instances = {"MainWindow": window} if window is not None else {}
        self._instances.update(instances)
        self.window = window

    def get_instance(self, name):
        return self._instances.get(name)


class TestWorkspaceCommands:
    def test_ui_preset_apply_can_skip_window_state(self):
        win = MagicMock()
        store = MagicMock()
        store.get_ui_preset.return_value = UIPreset(
            preset_id="p1",
            name="Current",
            window_state={"geometry": "old"},
            component_states={"grid": {"zoom": 1}},
        )

        with patch.object(workspace_commands.WorkspaceStore, "instance", return_value=store):
            workspace_commands.ui_preset_apply(_Ctx(win), preset_id="p1", restore_window_state=False)

        win.ui_coord.restore.assert_called_once_with(
            {"window_state": {"geometry": "old"}, "component_states": {"grid": {"zoom": 1}}},
            skip_window_state=True,
        )

    def test_ui_preset_overwrite_uses_current_ui_state(self):
        win = MagicMock()
        win.ui_coord.capture.return_value = {
            "window_state": {"geometry": "new"},
            "component_states": {"grid": {"zoom": 2}},
        }
        store = MagicMock()
        store.get_ui_preset.return_value = UIPreset(preset_id="p1", name="Current")
        store.update_ui_preset.return_value = True

        with patch.object(workspace_commands.WorkspaceStore, "instance", return_value=store):
            workspace_commands.ui_preset_overwrite(_Ctx(win), preset_id="p1")

        store.update_ui_preset.assert_called_once_with(
            "p1",
            {"geometry": "new"},
            {"grid": {"zoom": 2}},
        )

    def test_query_preset_apply_restores_sort_when_requested(self):
        win = MagicMock()
        store = MagicMock()
        store.get_query_preset.return_value = QueryPreset(
            preset_id="q1",
            name="Filter",
            bars=[BarSpec(filter="text", params={"keywords": "cat"})],
            sort_by="name",
            ascending=True,
        )

        with patch.object(workspace_commands.WorkspaceStore, "instance", return_value=store):
            workspace_commands.query_preset_apply(_Ctx(win), preset_id="q1", restore_sort=True)

        win.search_row_widget.set_sort.assert_called_once_with("name", True)

    def test_query_preset_apply_skips_sort_when_not_requested(self):
        win = MagicMock()
        store = MagicMock()
        store.get_query_preset.return_value = QueryPreset(
            preset_id="q1",
            name="Filter",
            bars=[BarSpec(filter="text", params={"keywords": "cat"})],
            sort_by="name",
            ascending=True,
        )

        with patch.object(workspace_commands.WorkspaceStore, "instance", return_value=store):
            workspace_commands.query_preset_apply(_Ctx(win), preset_id="q1", restore_sort=False)

        win.search_row_widget.set_sort.assert_not_called()

    def test_query_preset_overwrite_always_saves_sort_fields(self):
        win = MagicMock()
        win.query_coord.capture.return_value = {
            "bars": [{"filter": "text", "params": {"keywords": "dog"}}],
            "sort_by": "path",
            "ascending": False,
        }
        store = MagicMock()
        store.get_query_preset.return_value = QueryPreset(preset_id="q1", name="Filter")
        store.update_query_preset.return_value = True

        with patch.object(workspace_commands.WorkspaceStore, "instance", return_value=store):
            workspace_commands.query_preset_overwrite(_Ctx(win), preset_id="q1")

        args = store.update_query_preset.call_args[0]
        assert args[0] == "q1"
        assert args[2] == "path"
        assert args[3] is False

    def test_restore_slot_restores_window_slot(self):
        win = MagicMock()
        win.slot_id = "current"
        slot = WindowSlot(slot_id="slot1", ui={"u": 1}, path={"p": 1}, query={"q": 1})
        store = MagicMock()
        store.get_slot.return_value = slot

        with patch.object(workspace_commands.WorkspaceStore, "instance", return_value=store):
            workspace_commands.restore_slot(_Ctx(win), slot_id="slot1")

        win._save_slot.assert_called_once_with()
        win._restore_from_slot.assert_called_once_with(slot)

    def test_restore_slot_current_restores_without_saving_first(self):
        win = MagicMock()
        win.slot_id = "slot1"
        slot = WindowSlot(slot_id="slot1")
        store = MagicMock()
        store.get_slot.return_value = slot

        with patch.object(workspace_commands.WorkspaceStore, "instance", return_value=store):
            workspace_commands.restore_slot(_Ctx(win), slot_id="slot1")

        win._save_slot.assert_not_called()
        win._restore_from_slot.assert_called_once_with(slot)

    def test_restore_slot_other_slot_saves_current_before_restore(self):
        win = MagicMock()
        win.slot_id = "current"
        store = MagicMock()
        store.get_slot.return_value = WindowSlot(slot_id="slot1")

        with patch.object(workspace_commands.WorkspaceStore, "instance", return_value=store):
            workspace_commands.restore_slot(_Ctx(win), slot_id="slot1")

        win._save_slot.assert_called_once_with()
        win._restore_from_slot.assert_called_once_with(store.get_slot.return_value)

    def test_rename_slot_updates_store(self):
        win = MagicMock()
        store = MagicMock()
        store.get_slot.return_value = WindowSlot(slot_id="slot1", name="Old")
        store.rename_slot.return_value = True

        with patch.object(workspace_commands.WorkspaceStore, "instance", return_value=store):
            workspace_commands.rename_slot(_Ctx(win), slot_id="slot1", name="New")

        store.rename_slot.assert_called_once_with("slot1", "New")

    def test_rename_slot_missing_does_not_mutate_store(self):
        win = MagicMock()
        store = MagicMock()
        store.get_slot.return_value = None

        with patch.object(workspace_commands.WorkspaceStore, "instance", return_value=store):
            workspace_commands.rename_slot(_Ctx(win), slot_id="missing", name="New")

        store.rename_slot.assert_not_called()

    def test_delete_slot_forgets_saved_snapshot(self):
        store = MagicMock()
        store.get_slot.return_value = WindowSlot(slot_id="slot1")
        store.forget_slot_snapshot.return_value = True

        with patch.object(workspace_commands.WorkspaceStore, "instance", return_value=store):
            workspace_commands.delete_slot(_Ctx(MagicMock()), slot_id="slot1")

        store.forget_slot_snapshot.assert_called_once_with("slot1")
        store.get_active_slot_ids.assert_not_called()

    def test_delete_slot_missing_does_not_mutate_store(self):
        store = MagicMock()
        store.get_slot.return_value = None

        with patch.object(workspace_commands.WorkspaceStore, "instance", return_value=store):
            workspace_commands.delete_slot(_Ctx(MagicMock()), slot_id="missing")

        store.forget_slot_snapshot.assert_not_called()

    def test_new_window_reserves_slot_before_spawning_viewer(self):
        store = MagicMock()
        store.reserve_next_window_slot.return_value = ("slot1", WindowSlot(slot_id="slot1"), True)

        with patch.object(workspace_commands.WorkspaceStore, "instance", return_value=store), \
                patch.object(workspace_commands.AppProcess, "new_main") as new_main:
            workspace_commands.new_window(_Ctx())

        store.reserve_next_window_slot.assert_called_once_with()
        new_main.assert_called_once_with("--viewer", "--slot", "slot1")

    def test_new_window_falls_back_when_slot_reservation_fails(self):
        store = MagicMock()
        store.reserve_next_window_slot.side_effect = TimeoutError("locked")

        with patch.object(workspace_commands.WorkspaceStore, "instance", return_value=store), \
                patch.object(workspace_commands.AppProcess, "new_main") as new_main:
            workspace_commands.new_window(_Ctx())

        new_main.assert_called_once_with("--viewer")

    def test_new_window_releases_reserved_slot_when_spawn_fails(self):
        store = MagicMock()
        store.reserve_next_window_slot.return_value = ("slot1", WindowSlot(slot_id="slot1"), True)

        with patch.object(workspace_commands.WorkspaceStore, "instance", return_value=store), \
                patch.object(workspace_commands.AppProcess, "new_main", side_effect=RuntimeError("spawn failed")):
            with pytest.raises(RuntimeError, match="spawn failed"):
                workspace_commands.new_window(_Ctx())

        store.release_slot.assert_called_once_with("slot1")

    def test_popup_commands_call_toolbar_widget(self):
        tb = MagicMock()

        workspace_commands.show_ui_popup(_Ctx(WorkspaceToolbarWidget=tb))
        workspace_commands.show_path_popup(_Ctx(WorkspaceToolbarWidget=tb))
        workspace_commands.show_filter_popup(_Ctx(WorkspaceToolbarWidget=tb))
        workspace_commands.show_recent_popup(_Ctx(WorkspaceToolbarWidget=tb))

        tb.show_ui_popup.assert_called_once_with()
        tb.show_path_popup.assert_called_once_with()
        tb.show_filter_popup.assert_called_once_with()
        tb.show_recent_popup.assert_called_once_with()

    def test_workspace_menu_uses_popup_commands_instead_of_panel_toggle(self):
        from wafer.ui.layout.manager import LayoutManager

        items = workspace_commands.WorkspaceCommands.commands()
        paths = [item.path for item in items if hasattr(item, "path")]
        assert "ws.show_ui_popup" in paths
        assert "ws.show_path_popup" in paths
        assert "ws.show_filter_popup" in paths
        assert "ws.show_recent_popup" in paths
        assert "ws.rename_slot" in paths
        assert LayoutManager._command_id("Workspace") not in items
