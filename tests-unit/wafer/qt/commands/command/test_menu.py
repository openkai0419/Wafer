import pytest
from unittest.mock import MagicMock

from wafer.qt.commands.command.menu import (
    split_menu_path,
    is_sep_token,
    sep_path,
    is_section_token,
    section_parts,
    prefixed_path,
    prefixed_item_token,
    normalize_command_meta,
    MenuGroup,
    MenuHub,
)
from wafer.qt.commands.command.core import CommandMeta, CommandRegistry, register_command_defs


@pytest.fixture(autouse=True)
def _isolate_registry():
    reg = CommandRegistry.instance()
    prev = dict(reg._commands)
    yield
    reg._commands = prev


class TestSplitMenuPath:
    def test_simple(self):
        assert split_menu_path("file/open") == ["file", "open"]
        assert split_menu_path("/file//open/") == ["file", "open"]
        assert split_menu_path("cmd") == ["cmd"]

    def test_empty_string(self):
        assert split_menu_path("") == []


class TestIsSepToken:
    def test_separator(self):
        assert is_sep_token("-") is True

    def test_path_separator(self):
        assert is_sep_token("file/-") is True

    def test_not_separator(self):
        assert is_sep_token("file/open") is False

    def test_non_string(self):
        assert is_sep_token(42) is False

    def test_empty(self):
        assert is_sep_token("") is False


class TestSepPath:
    def test_simple_separator(self):
        assert sep_path("-") == []

    def test_path_separator(self):
        assert sep_path("file/-") == ["file"]

    def test_not_separator(self):
        assert sep_path("file/open") == []


class TestIsSectionToken:
    def test_section(self):
        assert is_section_token(":Label") is True

    def test_path_section(self):
        assert is_section_token("file/:Label") is True

    def test_not_section(self):
        assert is_section_token("file/open") is False

    def test_non_string(self):
        assert is_section_token(42) is False

    def test_empty(self):
        assert is_section_token("") is False


class TestSectionParts:
    def test_simple_section(self):
        assert section_parts(":Label") == ["Label"]

    def test_path_section(self):
        assert section_parts("file/:Label") == ["file", "Label"]

    def test_empty(self):
        assert section_parts("") == []


class TestPrefixedPath:
    def test_no_base(self):
        assert prefixed_path([], "cmd") == "cmd"

    def test_with_base(self):
        assert prefixed_path(["file"], "open") == "file/open"

    def test_already_prefixed(self):
        assert prefixed_path(["file"], "file/open") == "file/open"

    def test_different_prefix(self):
        assert prefixed_path(["file"], "view/zoom") == "file/view/zoom"


class TestPrefixedItemToken:
    def test_no_base(self):
        assert prefixed_item_token([], "cmd") == "cmd"

    def test_separator(self):
        result = prefixed_item_token(["file"], "-")
        assert result == "file/-"

    def test_section(self):
        result = prefixed_item_token(["file"], ":Label")
        assert result == "file/:Label"

    def test_command(self):
        result = prefixed_item_token(["file"], "open")
        assert result == "file/open"


class TestNormalizeCommandMeta:
    def test_basic(self):
        meta = CommandMeta(path="open", display="Open", func=lambda ctx: None)
        normalize_command_meta(["file"], meta)
        assert meta.id == "open"
        assert meta.path == "file/open"
        nested = CommandMeta(path="sub/deep/cmd", display="Cmd", func=lambda ctx: None)
        normalize_command_meta(["root"], nested)
        assert nested.id == "cmd"

    def test_no_path_raises(self):
        meta = CommandMeta(path="", display="X", func=lambda ctx: None)
        with pytest.raises(ValueError, match="path is required"):
            normalize_command_meta([], meta)

    def test_separator_path_raises(self):
        meta = CommandMeta(path="-", display="Sep", func=lambda ctx: None)
        with pytest.raises(ValueError, match="Invalid command path"):
            normalize_command_meta([], meta)

    def test_section_path_raises(self):
        meta = CommandMeta(path=":Label", display="Sec", func=lambda ctx: None)
        with pytest.raises(ValueError, match="Invalid command path"):
            normalize_command_meta([], meta)


class TestMenuHub:
    @pytest.fixture(autouse=True)
    def _reset_hub(self):
        hub = MenuHub.instance()
        prev_paths = dict(hub._all_paths)
        prev_by_menu = dict(hub._by_menu)
        prev_items = dict(hub._menu_items)
        yield
        hub._all_paths = prev_paths
        hub._by_menu = prev_by_menu
        hub._menu_items = prev_items
        hub._rebuild_folder_caches()

    def test_register_and_get_path(self):
        hub = MenuHub.instance()

        class FakeMenu:
            pass

        hub.register_paths(FakeMenu, {"open": "file/open"}, ["file/open"])
        assert hub.get_path_by_command_id("open") == "file/open"

    def test_get_path_unknown_command(self):
        hub = MenuHub.instance()
        assert hub.get_path_by_command_id("nonexistent") == ""

    def test_has_folder(self):
        hub = MenuHub.instance()

        class FakeMenu:
            pass

        hub.register_paths(FakeMenu, {"open": "file/open"}, ["file/open"])
        assert hub.has_folder("file")

    def test_has_folder_nonexistent(self):
        hub = MenuHub.instance()
        assert hub.has_folder("__nonexistent_folder__") is False

    def test_find_folder_prefixes_returns_nested_folder_path(self):
        hub = MenuHub.instance()

        class FakeMenu:
            pass

        hub.register_paths(FakeMenu, {"pf_a": "RootPF/Sub/pf_a", "pf_b": "RootPF/Sub/pf_b"}, ["RootPF/Sub/pf_a", "RootPF/Sub/pf_b"])
        assert "RootPF/Sub" in hub.find_folder_prefixes("Sub")

    def test_collect_items_by_folder(self):
        hub = MenuHub.instance()

        class FakeMenu:
            pass

        hub.register_paths(FakeMenu, {"col_x": "Collect/col_x", "col_y": "Collect/col_y"}, ["Collect/col_x", "Collect/col_y"])
        assert len(hub.collect_items_by_folder("Collect")) >= 2

    def test_menu_group_register_with_separator_registers_all_commands(self):
        class SepGroup(MenuGroup):
            NAME = "__TestSepGroup__"
            PRIORITY = 100

            @classmethod
            def commands(cls):
                return [
                    CommandMeta(path="__test_sep_cmd1__", display="Cmd 1", func=lambda ctx: None),
                    "-",
                    CommandMeta(path="__test_sep_cmd2__", display="Cmd 2", func=lambda ctx: None),
                ]

        try:
            SepGroup.register()
            reg = CommandRegistry.instance()
            assert reg.has_command("__test_sep_cmd1__")
            assert reg.has_command("__test_sep_cmd2__")
        finally:
            MenuGroup._flags.pop(SepGroup, None)


def _group(name: str, priority: int, items: list):
    return type(f"_G_{name.replace('/', '_')}_{priority}", (MenuGroup,), {"NAME": name, "PRIORITY": priority, "commands": classmethod(lambda cls: list(items))})


def _noop(ctx):
    return None


class TestNestedMenuGroups:
    def test_nested_name_places_commands_under_the_parent_folder(self):
        _group("__TNest__/Grid", 10, [":Grid", CommandMeta(path="__tnest_grid__", display="G", func=_noop)]).register()
        hub = MenuHub.instance()
        assert hub.get_path_by_command_id("__tnest_grid__") == "__TNest__/Grid/__tnest_grid__"
        assert hub.find_folder_prefixes("Grid") == ["__TNest__/Grid"]

    def test_no_separator_between_blocks_that_are_each_one_submenu(self):
        _group("__TSep__", 10, [CommandMeta(path="__tsep_direct__", display="D", func=_noop)]).register()
        _group("__TSep__/A", 20, [CommandMeta(path="__tsep_a__", display="A", func=_noop)]).register()
        _group("__TSep__/B", 30, [CommandMeta(path="__tsep_b__", display="B", func=_noop)]).register()
        assert MenuHub.instance().collect_items_by_folder("__TSep__") == [
            "__TSep__/__tsep_direct__",
            "__TSep__/-",
            "__TSep__/A/__tsep_a__",
            "__TSep__/B/__tsep_b__",
        ]

    def test_placing_a_registered_command_elsewhere_keeps_its_path_without_warning(self, monkeypatch):
        warnings = []
        monkeypatch.setattr("wafer.qt.commands.command.menu.AppLogger.warning", lambda msg, *a, **k: warnings.append(msg))
        _group("__TPlace__", 10, [CommandMeta(path="__tplace_cmd__", display="C", func=_noop)]).register()
        _group("__TPlaceOther__", 20, ["__tplace_cmd__"]).register()
        hub = MenuHub.instance()
        assert hub.get_path_by_command_id("__tplace_cmd__") == "__TPlace__/__tplace_cmd__"
        assert "__TPlaceOther__/__tplace_cmd__" in hub.collect_items_by_folder("__TPlaceOther__")
        assert warnings == []

    def test_definition_replaces_a_path_that_only_came_from_a_placement(self):
        _group("__TPlaceFirst__", 10, ["__tplace_late__"]).register()
        _group("__TPlaceDef__", 20, [CommandMeta(path="__tplace_late__", display="L", func=_noop)]).register()
        assert MenuHub.instance().get_path_by_command_id("__tplace_late__") == "__TPlaceDef__/__tplace_late__"

    def test_menu_order_moves_listed_blocks_after_the_unlisted_ones(self):
        first = _group("__TOrder__/First", 10, [CommandMeta(path="__torder_first__", display="F", func=_noop)])
        second = _group("__TOrder__/Second", 20, [CommandMeta(path="__torder_second__", display="S", func=_noop)])
        builtin = _group("__TOrder__", 5, [CommandMeta(path="__torder_builtin__", display="B", func=_noop)])
        first.register()
        second.register()
        builtin.register()
        hub = MenuHub.instance()
        prev = list(hub._menu_order)
        try:
            hub.set_menu_order(["__TOrder__/Second", "__TOrder__/First"])
            assert [s for s in hub.collect_items_by_folder("__TOrder__") if not s.endswith("/-")] == [
                "__TOrder__/__torder_builtin__",
                "__TOrder__/Second/__torder_second__",
                "__TOrder__/First/__torder_first__",
            ]
        finally:
            hub.set_menu_order(prev)
