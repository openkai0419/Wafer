import pytest
from PySide6 import QtWidgets

from wafer.qt.commands.command.core import CommandMeta, CommandRegistry, register_command_defs
from wafer.qt.commands.command.menu import MenuHub
from wafer.qt.commands.command.menu_builder import CommandMenuBuilder
from wafer.qt.commands.command.state import CommandOptionStore


@pytest.fixture(autouse=True)
def _isolate(tmp_path):
    reg = CommandRegistry.instance()
    prev_commands = dict(reg._commands)
    hub = MenuHub.instance()
    prev_paths, prev_by_menu, prev_items = dict(hub._all_paths), dict(hub._by_menu), dict(hub._menu_items)
    prev_store = CommandOptionStore._instance, CommandOptionStore._default_path
    CommandOptionStore._instance = None
    CommandOptionStore.configure(tmp_path / "opts.json")
    CommandMenuBuilder._menu_cache.clear()
    yield
    CommandMenuBuilder._menu_cache.clear()
    CommandOptionStore._instance, CommandOptionStore._default_path = prev_store
    reg._commands = prev_commands
    hub._all_paths, hub._by_menu, hub._menu_items = prev_paths, prev_by_menu, prev_items
    hub._rebuild_folder_caches()


def _register(folder, *cmd_ids, items=None):
    register_command_defs([CommandMeta(id=cid, display=cid, func=lambda ctx: None) for cid in cmd_ids])
    paths = {cid: f"{folder}/{cid}" for cid in cmd_ids}
    MenuHub.instance().register_paths(type(f"{folder}Group", (), {}), paths, items or list(paths.values()))


def test_build_creates_action_per_command(qtbot):
    _register("BuildMenu", "build_a", "build_b")
    parent = QtWidgets.QWidget()
    qtbot.addWidget(parent)

    menu = CommandMenuBuilder.instance().build(parent, ["build_a", "build_b"])

    assert isinstance(menu, QtWidgets.QMenu)
    assert len(menu.actions()) >= 2


def test_build_keeps_separator_between_paths(qtbot):
    items = ["SepMenu/sep_a", "-", "SepMenu/sep_b"]
    _register("SepMenu", "sep_a", "sep_b", items=items)
    parent = QtWidgets.QWidget()
    qtbot.addWidget(parent)

    menu = CommandMenuBuilder.instance().build(parent, items)

    assert any(a.isSeparator() for a in menu.actions())
