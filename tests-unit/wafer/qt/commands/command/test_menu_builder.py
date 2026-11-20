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


def section_texts(menu):
    return [label.text() for action in menu.actions() if isinstance(action, QtWidgets.QWidgetAction) for label in action.defaultWidget().findChildren(QtWidgets.QLabel)]


def test_an_action_on_a_section_path_is_a_header_that_can_skip_translation(qtbot, monkeypatch):
    from wafer.qt.commands.bridge import ActionKit, Menu
    from wafer.qt.commands.command import menu_builder

    translated = []
    original_t = menu_builder.t
    monkeypatch.setattr(menu_builder, "t", lambda text, **kwargs: (translated.append(text), original_t(text, **kwargs))[1])
    parent = QtWidgets.QWidget()
    qtbot.addWidget(parent)

    menu = Menu.session(parent).menu(
        [
            ActionKit.Action(path="Sub/:inline.head", display="User / Name", translate=False),
            ActionKit.Action(path="Sub/inline.row", display="Row", func=lambda ctx: None),
        ]
    ).build()

    submenu = next(action.menu() for action in menu.actions() if action.menu() is not None)
    assert section_texts(submenu)[0] == "User / Name"
    assert "User / Name" not in translated and "Row" in translated


@pytest.mark.parametrize(
    "extra",
    [{"display": ""}, {"display": "Head", "func": lambda ctx: None}, {"display": "Head", "checked": lambda: True}],
)
def test_a_header_action_needs_a_display_and_takes_no_func_or_checked(extra):
    from wafer.qt.commands.bridge import ActionKit
    from wafer.qt.commands.command.maker import MenuMaker

    with pytest.raises(ValueError):
        MenuMaker._action_to_resolved(ActionKit.Action(path="Sub/:inline.head", **extra))


def test_a_failing_command_is_logged_with_its_traceback(qtbot, monkeypatch):
    def boom(ctx):
        raise AttributeError("boom")

    register_command_defs([CommandMeta(id="exec_fail", display="exec_fail", func=boom)])
    warnings = []
    monkeypatch.setattr("wafer.qt.commands.command.menu_builder.AppLogger.warning", lambda msg, *a, **k: warnings.append(k.get("exc")))

    CommandMenuBuilder.instance()._execute("exec_fail")

    assert len(warnings) == 1 and isinstance(warnings[0], AttributeError)


def test_a_section_header_uses_the_theme_text_color(qtbot):
    from wafer.qt.theme import ThemeManager

    parent = QtWidgets.QWidget()
    qtbot.addWidget(parent)

    action = CommandMenuBuilder.instance()._create_section_action(parent, "Head")
    label = action.defaultWidget().findChild(QtWidgets.QLabel)

    assert "gray" not in label.styleSheet()
    assert ThemeManager.instance().palette.text_secondary in label.styleSheet()
