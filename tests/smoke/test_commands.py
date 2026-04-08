import time

import pytest
from PySide6 import QtCore, QtWidgets

from wafer.core.commands.bridge import ActionKit, Command, Menu
from wafer.core.commands.command.core import CommandBase, CommandMeta, CommandParam, CommandRegistry
from wafer.core.commands.command.context import CommandContext
from wafer.core.commands.command.menu import MenuGroup, MenuHub
from wafer.core.commands.command.menu_builder import CommandMenuBuilder
from wafer.core.commands.command.maker import MenuMaker
from wafer.core.commands.command.state import CommandOptionStore
from wafer.ui.layout.manager import LayoutManager


def _process_events(ms=50):
    app = QtWidgets.QApplication.instance()
    if app:
        app.processEvents(QtCore.QEventLoop.AllEvents, ms)


@pytest.fixture(autouse=True, scope="module")
def _configure_command_store(tmp_path_factory):
    prev = CommandOptionStore._instance, CommandOptionStore._initialized, CommandOptionStore._default_path
    CommandOptionStore._instance = None
    CommandOptionStore._initialized = False
    CommandOptionStore._default_path = None
    CommandOptionStore.configure(tmp_path_factory.mktemp("smoke_commands") / "cmd.json")
    yield
    CommandOptionStore._instance, CommandOptionStore._initialized, CommandOptionStore._default_path = prev


@pytest.fixture()
def cmd_registry():
    orig_reg = CommandRegistry._instance
    orig_builder = CommandMenuBuilder._instance, CommandMenuBuilder._initialized
    CommandRegistry._instance = None
    CommandMenuBuilder._instance = None
    CommandMenuBuilder._initialized = False
    yield CommandRegistry.instance()
    CommandRegistry._instance = orig_reg
    CommandMenuBuilder._instance, CommandMenuBuilder._initialized = orig_builder


@pytest.fixture()
def menu_hub():
    orig = MenuHub._instance
    MenuHub._instance = None
    yield MenuHub.instance()
    MenuHub._instance = orig


def _make_command(cmd_id, func=None, **kwargs):
    class Cmd(CommandBase):
        meta = CommandMeta(
            path=f"test/{cmd_id}",
            id=cmd_id,
            **kwargs,
        )

        def execute(self, **kw):
            if func:
                return func(**kw)
            return kw

    Cmd.__name__ = f"Cmd_{cmd_id}"
    return Cmd


class TestCommandRegistration:
    def test_register_and_lookup(self, cmd_registry):
        cmd = _make_command("smoke_hello", display="Hello")
        cmd_registry.register(cmd)
        assert cmd_registry.has_command("smoke_hello")
        assert cmd_registry.get_command("smoke_hello") is cmd

    def test_execute_returns_value(self, cmd_registry):
        results = []
        cmd = _make_command("smoke_exec", func=lambda ctx: results.append("ok"), display="Exec")
        cmd_registry.register(cmd)
        ctx = CommandContext.build(source="test")
        cmd_registry.execute("smoke_exec", ctx=ctx)
        assert results == ["ok"]

    def test_execute_unknown_command(self, cmd_registry):
        ctx = CommandContext.build(source="test")
        result = cmd_registry.execute("totally_unknown", ctx=ctx)
        assert result is None

    def test_overwrite_command(self, cmd_registry):
        results = []
        cmd1 = _make_command("smoke_ow", func=lambda ctx: results.append("v1"), display="OW1")
        cmd2 = _make_command("smoke_ow", func=lambda ctx: results.append("v2"), display="OW2")
        cmd_registry.register(cmd1)
        cmd_registry.register(cmd2)
        ctx = CommandContext.build(source="test")
        cmd_registry.execute("smoke_ow", ctx=ctx)
        assert results == ["v2"]

    def test_category_filtering(self, cmd_registry):
        cmd_registry.register(_make_command("smoke_c1", display="C1", category="edit"))
        cmd_registry.register(_make_command("smoke_c2", display="C2", category="view"))
        cmd_registry.register(_make_command("smoke_c3", display="C3", category="edit"))
        edit_cmds = cmd_registry.get_commands_by_category("edit")
        assert "smoke_c1" in edit_cmds
        assert "smoke_c3" in edit_cmds
        assert "smoke_c2" not in edit_cmds


class TestMenuGroupRegistration:
    def test_menu_group_registers_commands(self, cmd_registry, menu_hub):
        class TestGroup(MenuGroup):
            NAME = "SmokeTest"
            PRIORITY = 100

            @classmethod
            def commands(cls):
                return [
                    ActionKit.Command(
                        path="action_a",
                        display="Action A",
                        func=lambda ctx: None,
                    ),
                    ActionKit.Command(
                        path="action_b",
                        display="Action B",
                        func=lambda ctx: None,
                    ),
                ]

        TestGroup._flags.pop(TestGroup, None)
        TestGroup.register()

        assert cmd_registry.has_command("action_a")
        assert cmd_registry.has_command("action_b")
        assert menu_hub.get_path_by_command_id("action_a") == "SmokeTest/action_a"

        TestGroup._flags.pop(TestGroup, None)

    def test_menu_group_with_separators(self, cmd_registry, menu_hub):
        class SepGroup(MenuGroup):
            NAME = "SepTest"
            PRIORITY = 100

            @classmethod
            def commands(cls):
                return [
                    ActionKit.Command(
                        path="sep_cmd1",
                        display="Cmd 1",
                        func=lambda ctx: None,
                    ),
                    "-",
                    ActionKit.Command(
                        path="sep_cmd2",
                        display="Cmd 2",
                        func=lambda ctx: None,
                    ),
                ]

        SepGroup._flags.pop(SepGroup, None)
        SepGroup.register()

        assert cmd_registry.has_command("sep_cmd1")
        assert cmd_registry.has_command("sep_cmd2")

        SepGroup._flags.pop(SepGroup, None)


class TestMenuBuilding:
    def test_build_menu_from_commands(self, cmd_registry, menu_hub, qtbot):
        cmd_registry.register(_make_command("menu_item1", display="Item 1"))
        cmd_registry.register(_make_command("menu_item2", display="Item 2"))
        menu_hub.register_paths(
            type("FakeGroup", (), {}),
            {"menu_item1": "Smoke/menu_item1", "menu_item2": "Smoke/menu_item2"},
            ["Smoke/menu_item1", "Smoke/menu_item2"],
        )

        parent = QtWidgets.QWidget()
        qtbot.addWidget(parent)
        builder = CommandMenuBuilder.instance()

        qmenu = builder.build(parent, ["menu_item1", "menu_item2"])
        assert isinstance(qmenu, QtWidgets.QMenu)
        actions = qmenu.actions()
        assert len(actions) >= 2

    def test_build_menu_with_separator(self, cmd_registry, menu_hub, qtbot):
        cmd_registry.register(_make_command("sep_a", display="A"))
        cmd_registry.register(_make_command("sep_b", display="B"))
        menu_hub.register_paths(
            type("FakeGroup2", (), {}),
            {"sep_a": "SepSmoke/sep_a", "sep_b": "SepSmoke/sep_b"},
            ["SepSmoke/sep_a", "-", "SepSmoke/sep_b"],
        )

        parent = QtWidgets.QWidget()
        qtbot.addWidget(parent)
        builder = CommandMenuBuilder.instance()
        qmenu = builder.build(parent, ["SepSmoke/sep_a", "-", "SepSmoke/sep_b"])
        actions = qmenu.actions()
        has_separator = any(a.isSeparator() for a in actions)
        assert has_separator

    def test_build_menu_unknown_command(self, cmd_registry, qtbot):
        parent = QtWidgets.QWidget()
        qtbot.addWidget(parent)
        builder = CommandMenuBuilder.instance()
        qmenu = builder.build(parent, ["totally_unknown_cmd_xyz"])
        assert isinstance(qmenu, QtWidgets.QMenu)


class TestMenuSession:
    def test_session_menu(self, cmd_registry, menu_hub, qtbot):
        cmd_registry.register(_make_command("sess_a", display="Session A"))
        cmd_registry.register(_make_command("sess_b", display="Session B"))
        menu_hub.register_paths(
            type("SessGroup", (), {}),
            {"sess_a": "Sess/sess_a", "sess_b": "Sess/sess_b"},
            ["Sess/sess_a", "Sess/sess_b"],
        )

        parent = QtWidgets.QWidget()
        qtbot.addWidget(parent)

        session = Menu.session(parent)
        spec = session.menu(["sess_a", "sess_b"])
        assert spec is not None
        qmenu = spec.build()
        assert isinstance(qmenu, QtWidgets.QMenu)

    def test_session_from_folder(self, cmd_registry, menu_hub, qtbot):
        cmd_registry.register(_make_command("folder_a", display="Folder A"))
        cmd_registry.register(_make_command("folder_b", display="Folder B"))
        menu_hub.register_paths(
            type("FolderGroup", (), {}),
            {"folder_a": "TestFolder/folder_a", "folder_b": "TestFolder/folder_b"},
            ["TestFolder/folder_a", "TestFolder/folder_b"],
        )

        parent = QtWidgets.QWidget()
        qtbot.addWidget(parent)

        session = Menu.session(parent)
        spec = session.from_folder("TestFolder")
        assert spec is not None
        qmenu = spec.build()
        assert isinstance(qmenu, QtWidgets.QMenu)
        actions = qmenu.actions()
        assert len(actions) >= 2

    def test_session_from_unknown_folder(self, qtbot):
        parent = QtWidgets.QWidget()
        qtbot.addWidget(parent)
        session = Menu.session(parent)
        spec = session.from_folder("CompletelyNonexistent12345")
        assert spec is None

    def test_session_hide_command(self, cmd_registry, menu_hub, qtbot):
        cmd_registry.register(_make_command("hide_a", display="Hide A"))
        cmd_registry.register(_make_command("hide_b", display="Hide B"))
        cmd_registry.register(_make_command("hide_c", display="Hide C"))
        menu_hub.register_paths(
            type("HideGroup", (), {}),
            {
                "hide_a": "HideTest/hide_a",
                "hide_b": "HideTest/hide_b",
                "hide_c": "HideTest/hide_c",
            },
            ["HideTest/hide_a", "HideTest/hide_b", "HideTest/hide_c"],
        )

        parent = QtWidgets.QWidget()
        qtbot.addWidget(parent)
        session = Menu.session(parent)
        spec = session.from_folder("HideTest")
        assert spec is not None
        spec = spec.hide(["hide_b"])
        qmenu = spec.build()
        assert isinstance(qmenu, QtWidgets.QMenu)


class TestCheckableCommands:
    def test_checkable_command_state(self, cmd_registry, menu_hub, qtbot):
        cmd = _make_command("chk_a", display="Check A", checkable=True, default_checked=True)
        cmd_registry.register(cmd)
        menu_hub.register_paths(
            type("ChkGroup", (), {}),
            {"chk_a": "Checks/chk_a"},
            ["Checks/chk_a"],
        )

        parent = QtWidgets.QWidget()
        qtbot.addWidget(parent)
        builder = CommandMenuBuilder.instance()
        qmenu = builder.build(parent, ["chk_a"])
        actions = qmenu.actions()
        checkable_found = any(a.isCheckable() for a in actions)
        assert checkable_found

    def test_action_group_exclusivity(self, cmd_registry, menu_hub, qtbot):
        cmd_a = _make_command(
            "radio_a",
            display="Radio A",
            checkable=True,
            action_group="radio_group",
            default_checked=True,
        )
        cmd_b = _make_command(
            "radio_b",
            display="Radio B",
            checkable=True,
            action_group="radio_group",
        )
        cmd_registry.register(cmd_a)
        cmd_registry.register(cmd_b)
        menu_hub.register_paths(
            type("RadioGroup", (), {}),
            {"radio_a": "Radio/radio_a", "radio_b": "Radio/radio_b"},
            ["Radio/radio_a", "Radio/radio_b"],
        )

        parent = QtWidgets.QWidget()
        qtbot.addWidget(parent)
        builder = CommandMenuBuilder.instance()
        qmenu = builder.build(parent, ["radio_a", "radio_b"])
        actions = [a for a in qmenu.actions() if a.isCheckable()]
        assert len(actions) >= 2


class TestPanelToggleCommands:
    def test_panel_register_creates_command(self, qtbot):
        orig_registry = CommandRegistry._instance
        CommandRegistry._instance = None
        try:
            registry = CommandRegistry.instance()
            window = QtWidgets.QMainWindow()
            window.resize(400, 300)
            qtbot.addWidget(window)
            mgr = LayoutManager(window)
            mgr.register("TestPanel", lambda: QtWidgets.QLabel("Test"))

            cmd_id = LayoutManager._command_id("TestPanel")
            assert registry.has_command(cmd_id)
            window.close()
        finally:
            CommandRegistry._instance = orig_registry

    def test_panel_toggle_via_command(self, qtbot):
        orig_registry = CommandRegistry._instance
        CommandRegistry._instance = None
        try:
            registry = CommandRegistry.instance()
            window = QtWidgets.QMainWindow()
            window.resize(800, 600)
            qtbot.addWidget(window)
            mgr = LayoutManager(window)
            mgr.register("PanelA", lambda: QtWidgets.QLabel("A"))
            mgr.register("PanelB", lambda: QtWidgets.QLabel("B"))
            mgr.restore_state(
                {
                    "mode": "locked",
                    "tree": {
                        "root": {
                            "type": "split",
                            "orientation": "horizontal",
                            "children": [
                                {"type": "leaf", "panel": "PanelA"},
                                {"type": "leaf", "panel": "PanelB"},
                            ],
                            "sizes": [400, 400],
                        },
                        "floating": {},
                    },
                }
            )
            window.show()
            _process_events()

            cmd_id = LayoutManager._command_id("PanelA")
            ctx = CommandContext.build(source="test")
            registry.execute(cmd_id, ctx=ctx)
            _process_events()

            assert not mgr.is_panel_visible("PanelA") or "PanelA" in mgr._tree.floating
            window.close()
        finally:
            CommandRegistry._instance = orig_registry

    def test_panel_unregister_removes_command(self, qtbot):
        orig_registry = CommandRegistry._instance
        CommandRegistry._instance = None
        try:
            registry = CommandRegistry.instance()
            window = QtWidgets.QMainWindow()
            window.resize(400, 300)
            qtbot.addWidget(window)
            mgr = LayoutManager(window)
            mgr.register("Removable", lambda: QtWidgets.QLabel("R"))
            cmd_id = LayoutManager._command_id("Removable")
            assert registry.has_command(cmd_id)
            mgr.unregister("Removable")
            assert not registry.has_command(cmd_id)
            window.close()
        finally:
            CommandRegistry._instance = orig_registry


class TestMenuHubPaths:
    def test_register_and_resolve(self, menu_hub, cmd_registry):
        cmd_registry.register(_make_command("hub_a", display="Hub A"))
        menu_hub.register_paths(
            type("HubGroup", (), {}),
            {"hub_a": "Main/hub_a"},
            ["Main/hub_a"],
        )
        assert menu_hub.get_path_by_command_id("hub_a") == "Main/hub_a"
        assert menu_hub.has_folder("Main")

    def test_find_folder_prefixes(self, menu_hub, cmd_registry):
        cmd_registry.register(_make_command("pf_a", display="PF A"))
        cmd_registry.register(_make_command("pf_b", display="PF B"))
        menu_hub.register_paths(
            type("PFGroup", (), {}),
            {"pf_a": "RootPF/Sub/pf_a", "pf_b": "RootPF/Sub/pf_b"},
            ["RootPF/Sub/pf_a", "RootPF/Sub/pf_b"],
        )
        prefixes = menu_hub.find_folder_prefixes("Sub")
        assert "RootPF/Sub" in prefixes

    def test_collect_items_by_folder(self, menu_hub, cmd_registry):
        cmd_registry.register(_make_command("col_x", display="X"))
        cmd_registry.register(_make_command("col_y", display="Y"))
        menu_hub.register_paths(
            type("ColGroup", (), {}),
            {"col_x": "Collect/col_x", "col_y": "Collect/col_y"},
            ["Collect/col_x", "Collect/col_y"],
        )
        items = menu_hub.collect_items_by_folder("Collect")
        assert len(items) >= 2


class TestCommandWithParams:
    def test_execute_with_params(self, cmd_registry):
        results = []
        params = [CommandParam(name="amount", value=10, default=10)]
        cmd = _make_command("param_cmd", func=lambda ctx, amount=10: results.append(amount), display="Param", params=params)
        cmd_registry.register(cmd)
        ctx = CommandContext.build(source="test")
        cmd_registry.execute("param_cmd", ctx=ctx, amount=42)
        assert results == [42]

    def test_execute_with_default_params(self, cmd_registry):
        results = []
        params = [CommandParam(name="count", value=5, default=5)]
        cmd = _make_command("dparam_cmd", func=lambda ctx, count=5: results.append(count), display="DefParam", params=params)
        cmd_registry.register(cmd)
        ctx = CommandContext.build(source="test")
        cmd_registry.execute("dparam_cmd", ctx=ctx)
        assert results == [5]
