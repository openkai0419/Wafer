import pytest
from unittest.mock import MagicMock

from wafer.core.actions.command.menu import (
    split_menu_path,
    is_sep_token,
    sep_path,
    is_section_token,
    section_parts,
    prefixed_path,
    prefixed_item_token,
    normalize_command_meta,
    merge_dict_providers,
    MenuGroup,
    DragMenuGroup,
    MenuHub,
    discover_command_classes,
)
from wafer.core.actions.command.core import CommandMeta, CommandRegistry, register_command_defs


@pytest.fixture(autouse=True)
def _isolate_registry():
    reg = CommandRegistry.instance()
    prev = dict(reg._commands)
    yield
    reg._commands = prev


class TestSplitMenuPath:
    def test_simple(self):
        assert split_menu_path("file/open") == ["file", "open"]

    def test_leading_slash(self):
        assert split_menu_path("/file/open") == ["file", "open"]

    def test_trailing_slash(self):
        assert split_menu_path("file/open/") == ["file", "open"]

    def test_empty_segments_filtered(self):
        assert split_menu_path("file//open") == ["file", "open"]

    def test_single_segment(self):
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

    def test_nested_separator(self):
        assert sep_path("file/sub/-") == ["file", "sub"]

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

    def test_nested_section(self):
        assert section_parts("file/sub/:Label") == ["file", "sub", "Label"]

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

    def test_id_derived_from_last_segment(self):
        meta = CommandMeta(path="sub/deep/cmd", display="Cmd", func=lambda ctx: None)
        normalize_command_meta(["root"], meta)
        assert meta.id == "cmd"


class TestMergeDictProviders:
    def test_none_providers(self):
        assert merge_dict_providers(None, None) is None

    def test_single_provider(self):
        fn = merge_dict_providers(lambda: {"a": 1})
        assert fn() == {"a": 1}

    def test_multiple_providers_merged(self):
        fn = merge_dict_providers(lambda: {"a": 1}, lambda: {"b": 2})
        result = fn()
        assert result == {"a": 1, "b": 2}

    def test_later_provider_overwrites(self):
        fn = merge_dict_providers(lambda: {"a": 1}, lambda: {"a": 2})
        assert fn()["a"] == 2

    def test_provider_exception_handled(self):
        def broken():
            raise RuntimeError("fail")
        fn = merge_dict_providers(broken, lambda: {"ok": True})
        result = fn()
        assert result == {"ok": True}

    def test_provider_returns_none(self):
        fn = merge_dict_providers(lambda: None, lambda: {"ok": True})
        result = fn()
        assert result == {"ok": True}


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


class TestDiscoverCommandClasses:
    def test_finds_menu_group_subclass(self):
        import types
        mod = types.ModuleType("test_module")

        class TestMenu(MenuGroup):
            NAME = "test"

        mod.TestMenu = TestMenu
        result = discover_command_classes(mod)
        assert TestMenu in result

    def test_finds_drag_menu_group_subclass(self):
        import types
        mod = types.ModuleType("test_module")

        class TestDrag(DragMenuGroup):
            NAME = "test_drag"

        mod.TestDrag = TestDrag
        result = discover_command_classes(mod)
        assert TestDrag in result

    def test_excludes_base_classes(self):
        import types
        mod = types.ModuleType("test_module")
        mod.MenuGroup = MenuGroup
        mod.DragMenuGroup = DragMenuGroup
        result = discover_command_classes(mod)
        assert MenuGroup not in result
        assert DragMenuGroup not in result

    def test_deduplicates(self):
        import types
        mod = types.ModuleType("test_module")

        class TestMenu(MenuGroup):
            NAME = "test"

        mod.TestMenu = TestMenu
        result = discover_command_classes(mod, mod)
        count = sum(1 for x in result if x is TestMenu)
        assert count == 1
