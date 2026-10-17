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
    widget.set_files.assert_called_once_with(["a", "b"], "db")
    window._layout_manager.ensure_panel_visible.assert_called_once_with("Mapping")


def test_add_and_remove_use_selected_paths(monkeypatch):
    widget = MagicMock()
    window = MagicMock(database_path="db")
    monkeypatch.setattr(commands, "_panel", lambda w: widget)
    ctx = Ctx(**{"paths": ["a"], "instance:MainWindow": window})
    commands.mapping_add(ctx)
    widget.add_files.assert_called_once_with(["a"], "db")
    commands.mapping_remove(ctx)
    widget.remove_files.assert_called_once_with(["a"])


def test_set_without_paths_does_nothing(monkeypatch):
    widget = MagicMock()
    window = MagicMock(database_path="db")
    notifications = []
    monkeypatch.setattr(commands, "_panel", lambda w: widget)
    monkeypatch.setattr(commands.Notifier, "info", staticmethod(notifications.append))
    commands.mapping_set(Ctx(**{"instance:MainWindow": window}))
    widget.set_files.assert_not_called()
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
        "mapping.toggle_labels",
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


def test_view_commands_change_the_shared_settings():
    from extensions.mapping.view_settings import ViewSettings

    settings = ViewSettings.instance()
    ctx = Ctx()
    commands.image_scale_up(ctx, ratio=2.0)
    assert settings.image_scale == 2.0
    commands.image_scale_down(ctx, ratio=4.0)
    assert settings.image_scale == 0.5
    commands.toggle_selection_mode(ctx)
    assert settings.selection_mode == "group" and commands._group_mode_checked()
    commands.toggle_labels(ctx)
    assert settings.labels_shown is False and not commands._labels_checked()
    commands.toggle_thumbnails(ctx)
    assert settings.thumbnails_shown is False and not commands._thumbnails_checked()


def test_panel_commands_target_the_panel_the_command_came_from(monkeypatch):
    from extensions.mapping.widget import MappingWidget

    space, mapping = MagicMock(), MagicMock()
    monkeypatch.setattr(MappingWidget, "instance", classmethod(lambda cls: mapping))
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

    mapping = MagicMock(spec=MappingWidget)
    monkeypatch.setattr(MappingWidget, "instance", classmethod(lambda cls: mapping))
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
