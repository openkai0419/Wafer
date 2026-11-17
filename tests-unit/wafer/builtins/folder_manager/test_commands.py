from wafer.builtins.folder_manager import commands as commands_module
from wafer.builtins.folder_manager.commands import FolderManagerCommands, expand_matches, select_matches
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

    def expand_to_matches(self, select=False):
        self.calls.append(select)


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
