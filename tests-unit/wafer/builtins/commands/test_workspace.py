from unittest.mock import MagicMock, call, patch

import pytest

from wafer.builtins.commands import workspace as workspace_commands
from wafer.core.platform.workspace_lock import WorkspaceOwner
from wafer.core.store.workspace import BarSpec, QueryPreset, UIPreset, WindowSlot


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

    def test_open_slot_activates_open_workspace(self):
        win = MagicMock()
        win.slot_id = "current"
        with (
            patch.object(workspace_commands.WorkspaceLock, "open_slot_ids", return_value={"s2"}),
            patch.object(workspace_commands.WorkspaceLock, "read_owner", return_value=WorkspaceOwner(1, 55)),
            patch.object(workspace_commands, "activate_window") as activate,
            patch.object(workspace_commands.AppProcess, "new_main") as new_main,
        ):
            workspace_commands.open_slot(_Ctx(win), slot_id="s2")

        activate.assert_called_once_with(55)
        new_main.assert_not_called()

    def test_open_slot_spawns_closed_workspace(self):
        win = MagicMock()
        win.slot_id = "current"
        with (
            patch.object(workspace_commands.WorkspaceLock, "open_slot_ids", return_value=set()) as open_ids,
            patch.object(workspace_commands, "activate_window") as activate,
            patch.object(workspace_commands.AppProcess, "new_main") as new_main,
        ):
            workspace_commands.open_slot(_Ctx(win), slot_id="s2")

        open_ids.assert_called_once_with(["s2"])
        new_main.assert_called_once_with("--viewer", "--slot", "s2")
        activate.assert_not_called()

    def test_open_slot_ignores_current_window(self):
        win = MagicMock()
        win.slot_id = "s2"
        with (
            patch.object(workspace_commands.WorkspaceLock, "open_slot_ids") as open_ids,
            patch.object(workspace_commands, "activate_window") as activate,
            patch.object(workspace_commands.AppProcess, "new_main") as new_main,
        ):
            workspace_commands.open_slot(_Ctx(win), slot_id="s2")

        open_ids.assert_not_called()
        activate.assert_not_called()
        new_main.assert_not_called()

    def test_open_slot_without_owner_does_nothing(self):
        win = MagicMock()
        win.slot_id = "current"
        with (
            patch.object(workspace_commands.WorkspaceLock, "open_slot_ids", return_value={"s2"}),
            patch.object(workspace_commands.WorkspaceLock, "read_owner", return_value=None),
            patch.object(workspace_commands, "activate_window") as activate,
            patch.object(workspace_commands.AppProcess, "new_main") as new_main,
        ):
            workspace_commands.open_slot(_Ctx(win), slot_id="s2")

        activate.assert_not_called()
        new_main.assert_not_called()

    def test_workspace_menu_registers_open_slot_not_restore_slot(self):
        paths = [item.path for item in workspace_commands.WorkspaceCommands.commands() if hasattr(item, "path")]
        assert "ws.open_slot" in paths
        assert "ws.restore_slot" not in paths

    def test_rename_slot_updates_store(self):
        win = MagicMock()
        store = MagicMock()
        store.get_slot.return_value = WindowSlot(slot_id="slot1", name="Old")
        store.rename_slot.return_value = True

        with patch.object(workspace_commands.WorkspaceStore, "instance", return_value=store):
            workspace_commands.rename_slot(_Ctx(win), slot_id="slot1", name="New")

        store.rename_slot.assert_called_once_with("slot1", "New")

    def test_rename_slot_broadcasts_rename(self):
        win = MagicMock()
        win.slot_id = "current"
        store = MagicMock()
        store.get_slot.return_value = WindowSlot(slot_id="s2", name="Old")
        store.rename_slot.return_value = True

        with patch.object(workspace_commands.WorkspaceStore, "instance", return_value=store):
            workspace_commands.rename_slot(_Ctx(win), slot_id="s2", name="New")

        win._bridge.node.send.assert_called_once_with("slot.renamed", {"slot_id": "s2", "name": "New"}, dst="viewer")
        win._update_title.assert_not_called()

    def test_rename_current_slot_updates_own_title_without_broadcast(self):
        win = MagicMock()
        win.slot_id = "s2"
        win._slot_entry = WindowSlot(slot_id="s2", name="Old")
        store = MagicMock()
        store.get_slot.return_value = WindowSlot(slot_id="s2", name="Old")
        store.rename_slot.return_value = True

        with patch.object(workspace_commands.WorkspaceStore, "instance", return_value=store):
            workspace_commands.rename_slot(_Ctx(win), slot_id="s2", name="New")

        assert win._slot_entry.name == "New"
        win._update_title.assert_called_once_with()
        win._bridge.node.send.assert_not_called()

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

    def test_open_workspace_saves_then_spawns_picker(self):
        win = MagicMock()
        win.slot_id = "s1"
        order = MagicMock()
        order.attach_mock(win._save_slot, "save")
        with patch.object(workspace_commands.AppProcess, "new_main") as new_main:
            order.attach_mock(new_main, "spawn")
            workspace_commands.open_workspace(_Ctx(win))

        assert order.mock_calls == [
            call.save(),
            call.spawn("--viewer", "--pick", "--seed-slot", "s1"),
        ]

    def test_process_menu_has_open_workspace_instead_of_new_window(self):
        from wafer.builtins.commands.window import WindowRestartCommands

        commands = {item.path: item for item in WindowRestartCommands.commands() if hasattr(item, "path")}
        assert "ws.open_workspace" in commands
        assert "win.new_window" not in commands

    def test_workspace_menu_uses_popup_commands_instead_of_panel_toggle(self):
        from wafer.qt.layout.manager import LayoutManager

        items = workspace_commands.WorkspaceCommands.commands()
        paths = [item.path for item in items if hasattr(item, "path")]
        assert "ws.show_ui_popup" in paths
        assert "ws.show_path_popup" in paths
        assert "ws.show_filter_popup" in paths
        assert "ws.show_recent_popup" in paths
        assert "ws.rename_slot" in paths
        assert "ws.reset_panel_layout" not in paths
        assert LayoutManager._command_id("Workspace") not in items
