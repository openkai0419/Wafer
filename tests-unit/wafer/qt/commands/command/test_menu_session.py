import pytest
from PySide6 import QtWidgets

from wafer.qt.commands.command.core import CommandMeta, CommandRegistry, register_command_defs
from wafer.qt.commands.command.menu import MenuHub
from wafer.qt.commands.command.menu_builder import CommandMenuBuilder
from wafer.qt.commands.command.menu_session import MenuSession
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


def _register(folder, *cmd_ids):
    register_command_defs([CommandMeta(id=cid, display=cid, func=lambda ctx: None) for cid in cmd_ids])
    paths = {cid: f"{folder}/{cid}" for cid in cmd_ids}
    MenuHub.instance().register_paths(type(f"{folder}Group", (), {}), paths, list(paths.values()))


@pytest.fixture()
def parent(qtbot):
    w = QtWidgets.QWidget()
    qtbot.addWidget(w)
    return w


def test_from_folder_builds_folder_commands(parent):
    _register("SessionFolder", "folder_a", "folder_b")

    spec = MenuSession(parent).from_folder("SessionFolder")

    assert spec is not None
    menu = spec.build()
    assert isinstance(menu, QtWidgets.QMenu)
    assert len(menu.actions()) >= 2


def test_from_unknown_folder_returns_none(parent):
    assert MenuSession(parent).from_folder("CompletelyNonexistent12345") is None


def test_hide_removes_command_from_folder_menu(parent):
    _register("SessionHide", "hide_a", "hide_b", "hide_c")

    full = MenuSession(parent).from_folder("SessionHide").build()
    hidden = MenuSession(parent).from_folder("SessionHide").hide(["hide_b"]).build()

    assert isinstance(hidden, QtWidgets.QMenu)
    assert len(hidden.actions()) == len(full.actions()) - 1
