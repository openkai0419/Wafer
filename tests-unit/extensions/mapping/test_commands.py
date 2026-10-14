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
    assert view == {
        "mapping.select_all",
        "mapping.drill_down",
        "mapping.drill_up",
        "mapping.relayout_selection",
        "mapping.relayout_selection",
        "mapping.recompute",
        "mapping.space_mode",
        "mapping.space_mode",
        "mapping.toggle_grouping",
        "mapping.image_scale_up",
        "mapping.image_scale_down",
        "mapping.selection_mode",
    }


def test_image_scale_commands_take_a_ratio():
    metas = {c.path: c for c in MappingViewCommands.commands() if not isinstance(c, str)}
    for path in ("mapping.image_scale_up", "mapping.image_scale_down"):
        (param,) = metas[path].params
        assert (param.name, param.default) == ("ratio", 1.1)


def test_image_scale_commands_call_widget():
    widget = MagicMock()
    ctx = Ctx(**{"instance:MappingWidget": widget})
    commands.image_scale_up(ctx, ratio=1.5)
    commands.image_scale_down(ctx)
    widget.image_scale_up.assert_called_once_with(1.5)
    widget.image_scale_down.assert_called_once_with(1.1)


def test_selection_mode_command_toggles():
    widget = MagicMock(selection_mode="single")
    ctx = Ctx(**{"instance:MappingWidget": widget})
    commands.toggle_selection_mode(ctx)
    widget.set_selection_mode.assert_called_once_with("group")
    widget.selection_mode = "group"
    commands.toggle_selection_mode(ctx)
    widget.set_selection_mode.assert_called_with("single")


def test_relayout_selection_command_calls_widget():
    widget = MagicMock()
    commands.relayout_selection(Ctx(**{"instance:MappingWidget": widget}))
    widget.relayout_selection.assert_called_once_with()


def test_space_mode_command_toggles():
    widget = MagicMock(space_mode="space")
    ctx = Ctx(**{"instance:MappingWidget": widget})
    commands.toggle_space_mode(ctx)
    widget.set_space_mode.assert_called_once_with("live")
    widget.space_mode = "live"
    commands.toggle_space_mode(ctx)
    widget.set_space_mode.assert_called_with("space")


def test_space_mode_checked_follows_effective_mode(monkeypatch):
    from extensions.mapping.widget import MappingWidget

    widget = MagicMock()
    monkeypatch.setattr(MappingWidget, "instance", classmethod(lambda cls: widget))
    widget.effective_mode.return_value = "space"
    assert commands._space_mode_checked() is True
    widget.effective_mode.return_value = "live"
    assert commands._space_mode_checked() is False
    monkeypatch.setattr(MappingWidget, "instance", classmethod(lambda cls: None))
    assert commands._space_mode_checked() is False


def test_relayout_selection_command_calls_widget():
    widget = MagicMock()
    commands.relayout_selection(Ctx(**{"instance:MappingWidget": widget}))
    widget.relayout_selection.assert_called_once_with()


def test_space_mode_command_toggles():
    widget = MagicMock(space_mode="space")
    ctx = Ctx(**{"instance:MappingWidget": widget})
    commands.toggle_space_mode(ctx)
    widget.set_space_mode.assert_called_once_with("live")
    widget.space_mode = "live"
    commands.toggle_space_mode(ctx)
    widget.set_space_mode.assert_called_with("space")


def test_space_mode_checked_follows_effective_mode(monkeypatch):
    from extensions.mapping.widget import MappingWidget

    widget = MagicMock()
    monkeypatch.setattr(MappingWidget, "instance", classmethod(lambda cls: widget))
    widget.effective_mode.return_value = "space"
    assert commands._space_mode_checked() is True
    widget.effective_mode.return_value = "live"
    assert commands._space_mode_checked() is False
    monkeypatch.setattr(MappingWidget, "instance", classmethod(lambda cls: None))
    assert commands._space_mode_checked() is False
