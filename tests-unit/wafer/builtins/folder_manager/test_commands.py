from wafer.builtins.folder_manager import commands as commands_module
from wafer.builtins.folder_manager.commands import FolderManagerCommands, collapse_all, expand_matches, select_matches, toggle_matches_only
from wafer.qt.commands.binding.instance_registry import InstanceRegistry
from wafer.qt.commands.bridge import Command
from wafer.qt.commands.command.core import CommandRegistry


class FakeCtx:
    def __init__(self, instance):
        self.instance = instance
        self.asked = []

    def get_instance(self, name):
        self.asked.append(name)
        return self.instance


class FakePanel:
    def __init__(self):
        self.calls = []
        self.matches_only = False

    def expand_to_matches(self, select=False):
        self.calls.append(select)

    def set_matches_only(self, on):
        self.matches_only = on

    def collapse_all(self):
        self.calls.append("collapse")


def test_commands_are_registered(qtbot):
    FolderManagerCommands.register()
    registry = CommandRegistry.instance()
    assert registry.has_command("folder_manager.expand_matches")
    assert registry.has_command("folder_manager.select_matches")


def test_commands_run_on_the_open_panel():
    panel = FakePanel()
    ctx = FakeCtx(panel)

    expand_matches(ctx)
    select_matches(ctx)

    assert panel.calls == [False, True]
    assert ctx.asked == ["FolderManager", "FolderManager"]


def test_commands_without_the_panel_tell_the_user(monkeypatch):
    notices = []
    monkeypatch.setattr(commands_module.Notifier, "info", lambda text, *args, **kwargs: notices.append(text))

    expand_matches(FakeCtx(None))

    assert len(notices) == 1


def test_commands_are_available_in_the_viewer_and_the_tray():
    assert FolderManagerCommands.SCOPE == "*"


def test_matches_only_command_toggles_and_reports_checked(qtbot, monkeypatch):
    FolderManagerCommands.register()
    panel = FakePanel()
    registry = InstanceRegistry.instance()
    monkeypatch.setattr(registry, "get_one", lambda name: None)
    assert CommandRegistry.instance().get_command("folder_manager.matches_only").meta.checkable
    assert Command.get_checked("folder_manager.matches_only") is False

    monkeypatch.setattr(registry, "get_one", lambda name: panel if name == "FolderManager" else None)
    toggle_matches_only(FakeCtx(panel))
    assert panel.matches_only is True
    assert Command.get_checked("folder_manager.matches_only") is True
    toggle_matches_only(FakeCtx(panel))
    assert panel.matches_only is False
    assert Command.get_checked("folder_manager.matches_only") is False


def test_collapse_all_command_runs_on_the_open_panel():
    FolderManagerCommands.register()
    assert CommandRegistry.instance().has_command("folder_manager.collapse_all")
    panel = FakePanel()

    collapse_all(FakeCtx(panel))

    assert panel.calls == ["collapse"]


def test_matches_only_and_collapse_without_the_panel_tell_the_user(monkeypatch):
    notices = []
    monkeypatch.setattr(commands_module.Notifier, "info", lambda text, *args, **kwargs: notices.append(text))

    toggle_matches_only(FakeCtx(None))
    collapse_all(FakeCtx(None))

    assert len(notices) == 2
