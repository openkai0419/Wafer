import pytest

from source.actions.command.menu import MenuHub
from source.actions.command.maker import MenuMaker
from source.actions.command.core import CommandMeta


def _register_dummy_menu():
    hub = MenuHub()

    class _Dummy:
        pass

    cmd_paths = {
        "t.file.open": "file/t.file.open",
        "t.file.run": "file/t.file.run",
        "t.file.hide": "file/t.file.hide",
    }
    items = [
        "t.file.open",
        "t.file.run",
        "-",
        ":File",
        "t.file.hide",
    ]
    hub.register_paths(_Dummy, cmd_paths, items)


def test_menuplan_insert_by_id_applies_to_each_occurrence():
    _register_dummy_menu()
    maker = MenuMaker()
    plan = maker.menu(["t.file.open", "t.file.open"]).insert("t.file.open", [":X", "-", "t.file.run"])
    assert plan.resolve_tokens() == [
        "t.file.open",
        ":X",
        "-",
        "t.file.run",
        "t.file.open",
        ":X",
        "-",
        "t.file.run",
    ]


def test_menuplan_insert_by_path_targets_single_token_match():
    _register_dummy_menu()
    maker = MenuMaker()
    plan = maker.menu(["file/t.file.open", "t.file.open"]).insert("file/t.file.open", ["t.file.run"])
    assert plan.resolve_tokens() == ["file/t.file.open", "t.file.run", "t.file.open"]


def test_menuplan_hide_not_found_is_error():
    _register_dummy_menu()
    maker = MenuMaker()
    with pytest.raises(ValueError):
        maker.menu(["t.file.open"]).hide(["t.file.missing"])


def test_menuplan_insert_not_found_is_error():
    _register_dummy_menu()
    maker = MenuMaker()
    with pytest.raises(ValueError):
        maker.menu(["t.file.open"]).insert("t.file.missing", ["t.file.run"])


def test_menuplan_add_appends_items():
    _register_dummy_menu()
    maker = MenuMaker()
    plan = maker.menu(["t.file.open"]).add(["-", "t.file.run"])
    assert plan.resolve_tokens() == ["t.file.open", "-", "t.file.run"]


def test_menuplan_add_accepts_inline_command_meta():
    _register_dummy_menu()
    maker = MenuMaker()
    meta = CommandMeta(path="inline/t.inline", display="Inline", func=lambda ctx=None: None)
    plan = maker.menu(["t.file.open"]).add([meta])
    assert plan.resolve_tokens()[-1] == "inline/t.inline"
