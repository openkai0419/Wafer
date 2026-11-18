from wafer.builtins.folder_manager import commands as commands_module
from wafer.builtins.folder_manager.commands import FolderManagerCommands, collapse_all, select_matches, toggle_matches_only
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
    def __init__(self, visible=True):
        self.calls = []
        self.matches_only = False
        self.visible = visible

    def isVisible(self):
        return self.visible

    def select_matches(self):
        self.calls.append("select")

    def set_matches_only(self, on):
        self.matches_only = on

    def collapse_all(self):
        self.calls.append("collapse")


def test_commands_are_registered(qtbot):
    FolderManagerCommands.register()
    registry = CommandRegistry.instance()
    assert registry.has_command("folder_manager.select_matches")
    assert not registry.has_command("folder_manager.expand_matches")
    assert "folder_manager.expand_matches" not in [getattr(item, "path", item) for item in FolderManagerCommands.commands()]


def test_commands_run_on_the_open_panel():
    panel = FakePanel()
    ctx = FakeCtx(panel)

    select_matches(ctx)

    assert panel.calls == ["select"]
    assert ctx.asked == ["FolderManager"]


def opened_panels(monkeypatch, panel):
    opened = []
    monkeypatch.setattr(commands_module, "show_panel", lambda name="", *, toggle=True: opened.append((name, toggle)) or panel)
    return opened


def test_commands_open_the_panel_when_it_is_not_open_and_then_act(monkeypatch):
    panel = FakePanel()
    opened = opened_panels(monkeypatch, panel)

    select_matches(FakeCtx(None))
    toggle_matches_only(FakeCtx(None))
    collapse_all(FakeCtx(FakePanel(visible=False)))

    assert opened == [("Folder Manager", False)] * 3
    assert panel.calls == ["select", "collapse"] and panel.matches_only


def test_commands_do_nothing_when_the_panel_cannot_be_opened(monkeypatch):
    opened = opened_panels(monkeypatch, None)

    select_matches(FakeCtx(None))

    assert opened == [("Folder Manager", False)]


def test_commands_are_available_in_the_viewer_and_the_tray():
    assert FolderManagerCommands.SCOPE == "*"


def test_matches_only_command_toggles_and_reports_checked(qtbot, monkeypatch):
    FolderManagerCommands.register()
    panel = FakePanel()
    monkeypatch.setattr(InstanceRegistry, "get_one", lambda self, name: None)
    assert CommandRegistry.instance().get_command("folder_manager.matches_only").meta.checkable
    assert Command.get_checked("folder_manager.matches_only") is False

    monkeypatch.setattr(InstanceRegistry, "get_one", lambda self, name: panel if name == "FolderManager" else None)
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
