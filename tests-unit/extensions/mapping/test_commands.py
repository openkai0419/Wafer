from unittest.mock import MagicMock

from extensions.mapping import commands
from extensions.mapping.commands import MappingGridCommands, MappingViewCommands, ctx_paths


class Ctx(dict):
    def get_instance(self, name, default=None):
        return self.get(f"instance:{name}", default)


def test_ctx_paths_prefers_paths_and_dedups():
    assert ctx_paths(Ctx(paths=["a", "b", "a"], path="z")) == ["a", "b"]
    assert ctx_paths(Ctx(path="z")) == ["z"]
    assert ctx_paths(Ctx()) == []


def test_set_opens_panel_with_selected_paths(monkeypatch):
    widget = MagicMock()
    window = MagicMock(database_path="db")
    monkeypatch.setattr(commands, "_panel", lambda w: widget)
    commands.mapping_set(Ctx(**{"paths": ["a", "b"], "instance:MainWindow": window}))
    widget.map_tab.set_files.assert_called_once_with(["a", "b"], "db")
    widget.show_map.assert_called_once_with()
    window._layout_manager.ensure_panel_visible.assert_called_once_with("Mapping")


def test_add_and_remove_use_selected_paths(monkeypatch):
    widget = MagicMock()
    window = MagicMock(database_path="db")
    monkeypatch.setattr(commands, "_panel", lambda w: widget)
    ctx = Ctx(**{"paths": ["a"], "instance:MainWindow": window})
    commands.mapping_add(ctx)
    widget.map_tab.add_files.assert_called_once_with(["a"], "db")
    commands.mapping_remove(ctx)
    widget.map_tab.remove_files.assert_called_once_with(["a"])


def test_set_without_paths_does_nothing(monkeypatch):
    widget = MagicMock()
    window = MagicMock(database_path="db")
    notifications = []
    monkeypatch.setattr(commands, "_panel", lambda w: widget)
    monkeypatch.setattr(commands.Notifier, "info", staticmethod(notifications.append))
    commands.mapping_set(Ctx(**{"instance:MainWindow": window}))
    widget.map_tab.set_files.assert_not_called()
    assert notifications == ["No files selected"]


def test_command_ids():
    grid = {c.path.split("/")[-1] for c in MappingGridCommands.commands() if not isinstance(c, str)}
    view = {c.path for c in MappingViewCommands.commands() if not isinstance(c, str)}
    assert grid == {"mapping.set", "mapping.add", "mapping.remove"}
    assert MappingGridCommands.NAME == "File"
    assert view == {
        "mapping.select_all",
        "mapping.frame_selection",
        "mapping.drill_down",
        "mapping.drill_up",
        "mapping.recompute",
        "mapping.toggle_thumbnails",
        "mapping.image_scale_up",
        "mapping.image_scale_down",
        "mapping.selection_mode",
    }


def test_image_scale_commands_take_a_ratio():
    metas = {c.path: c for c in MappingViewCommands.commands() if not isinstance(c, str)}
    for path in ("mapping.image_scale_up", "mapping.image_scale_down"):
        (param,) = metas[path].params
        assert (param.name, param.default) == ("ratio", 1.1)


def test_image_scale_commands_change_the_shared_settings():
    from extensions.mapping.view_settings import ViewSettings

    settings = ViewSettings.instance()
    commands.image_scale_up(Ctx(), ratio=2.0)
    assert settings.image_scale == 2.0
    commands.image_scale_down(Ctx(), ratio=4.0)
    assert settings.image_scale == 0.5


def test_view_commands_toggle_the_tab_they_came_from(monkeypatch):
    from types import SimpleNamespace

    from extensions.mapping.view_settings import TabSettings

    panel, other = SimpleNamespace(tab=TabSettings()), SimpleNamespace(tab=TabSettings())
    monkeypatch.setattr(commands, "map_panel", lambda ctx: ctx.get("map_panel", panel))
    ctx = Ctx(map_panel=panel)
    commands.toggle_thumbnails(ctx)
    commands.toggle_selection_mode(ctx)
    assert not panel.tab.thumbnails_shown and panel.tab.selection_mode == "single"
    assert other.tab.thumbnails_shown and other.tab.selection_mode == "group"
    assert not commands._thumbnails_checked() and not commands._group_mode_checked()


def test_panel_commands_target_the_panel_the_command_came_from(monkeypatch):
    from extensions.mapping.panel import MappingPanel

    space, mapping = MagicMock(), MagicMock()
    monkeypatch.setattr(MappingPanel, "instance", classmethod(lambda cls: MagicMock(current_map=lambda: mapping)))
    commands.select_all(Ctx(map_panel=space))
    commands.frame_selection(Ctx(map_panel=space))
    space.map_view.frame_selection.assert_called_once_with()
    commands.recompute(Ctx(map_panel=space))
    space.select_all.assert_called_once_with()
    space.refresh.assert_called_once_with()
    commands.select_all(Ctx())
    mapping.select_all.assert_called_once_with()


def test_drill_commands_only_drive_the_mapping_panel(monkeypatch):
    from extensions.mapping.widget import MappingWidget

    from extensions.mapping.panel import MappingPanel

    mapping = MagicMock(spec=MappingWidget)
    monkeypatch.setattr(MappingPanel, "instance", classmethod(lambda cls: MagicMock(current_map=lambda: mapping)))
    space = MagicMock()
    commands.drill_down(Ctx(map_panel=space))
    commands.drill_up(Ctx(map_panel=space))
    space.drill_down.assert_not_called()
    mapping.drill_down.assert_not_called()
    mapping.drill_up.assert_not_called()
    commands.drill_down(Ctx(map_panel=mapping))
    commands.drill_up(Ctx())
    mapping.drill_down.assert_called_once_with()
    mapping.drill_up.assert_called_once_with()


def test_set_shows_the_files_on_the_map_tab(qtbot, monkeypatch):
    from extensions.mapping.panel import MappingPanel

    panel = MappingPanel()
    qtbot.addWidget(panel)
    panel.show_settings()
    received = []
    monkeypatch.setattr(panel.map_tab, "set_files", lambda paths, db: received.append((paths, db)))
    window = MagicMock(database_path="db")
    window._layout_manager.panel_widget.return_value = panel
    commands.mapping_set(Ctx(**{"paths": ["c:/a.png"], "instance:MainWindow": window}))
    assert received == [(["c:/a.png"], "db")] and panel.current_map() is panel.map_tab


def test_there_is_no_label_command():
    from extensions.mapping.view_settings import TabSettings

    assert "mapping.toggle_labels" not in {c.path for c in MappingViewCommands.commands() if not isinstance(c, str)}
    assert "labels" not in TabSettings().to_dict()


def test_both_tabs_select_whole_groups_by_default():
    from extensions.mapping.view_settings import TabSettings

    assert TabSettings().selection_mode == "group"
