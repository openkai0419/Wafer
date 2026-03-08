import pytest

from wafer.core.actions.command.menu import MenuHub
from wafer.core.actions.command.maker import MenuMaker
from wafer.core.actions.command.core import CommandMeta


def _register_dummy_menu():
    hub = MenuHub.instance()

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


def _unique_roots_from_tokens(tokens):
    seen = set()
    roots = []
    for t in tokens:
        if "/" not in t or t.startswith(":") or t == "-":
            continue
        r = t.split("/")[0]
        if r not in seen:
            seen.add(r)
            roots.append(r)
    return roots


class TestAllRootsPriority:

    @pytest.fixture(autouse=True)
    def _clean_hub(self):
        hub = MenuHub.instance()
        saved = (
            dict(hub._all_paths), dict(hub._by_menu),
            dict(hub._menu_items), dict(hub._folder_blocks),
            set(hub._folder_set), dict(hub._folder_prefix_map),
        )
        hub._all_paths.clear()
        hub._by_menu.clear()
        hub._menu_items.clear()
        hub._folder_blocks.clear()
        hub._folder_set.clear()
        hub._folder_prefix_map.clear()
        yield
        hub._all_paths, hub._by_menu, hub._menu_items, hub._folder_blocks, hub._folder_set, hub._folder_prefix_map = saved

    @staticmethod
    def _make_group(name, priority, items, cmd_paths):
        ns = {"NAME": name, "PRIORITY": priority}
        cls = type(f"_G_{name}", (), ns)
        return cls, cmd_paths, items

    def _register(self, hub, groups):
        for cls, cmd_paths, items in groups:
            hub.register_paths(cls, cmd_paths, items)

    def test_roots_sorted_by_priority(self):
        hub = MenuHub.instance()
        groups = [
            self._make_group("Bravo", 20, ["Bravo/b.cmd"], {"b.cmd": "Bravo/b.cmd"}),
            self._make_group("Alpha", 10, ["Alpha/a.cmd"], {"a.cmd": "Alpha/a.cmd"}),
            self._make_group("Charlie", 30, ["Charlie/c.cmd"], {"c.cmd": "Charlie/c.cmd"}),
        ]
        self._register(hub, groups)
        maker = MenuMaker()
        plan = maker.all_roots()
        assert _unique_roots_from_tokens(plan.resolve_tokens()) == ["Alpha", "Bravo", "Charlie"]

    def test_same_priority_preserves_insertion_order(self):
        hub = MenuHub.instance()
        groups = [
            self._make_group("Zulu", 0, ["Zulu/z.cmd"], {"z.cmd": "Zulu/z.cmd"}),
            self._make_group("Alpha", 0, ["Alpha/a.cmd"], {"a.cmd": "Alpha/a.cmd"}),
            self._make_group("Mid", 0, ["Mid/m.cmd"], {"m.cmd": "Mid/m.cmd"}),
        ]
        self._register(hub, groups)
        maker = MenuMaker()
        plan = maker.all_roots()
        assert _unique_roots_from_tokens(plan.resolve_tokens()) == ["Zulu", "Alpha", "Mid"]

    def test_high_priority_at_bottom(self):
        hub = MenuHub.instance()
        groups = [
            self._make_group("Ext", 1000, ["Ext/x.cmd"], {"x.cmd": "Ext/x.cmd"}),
            self._make_group("Core", 10, ["Core/c.cmd"], {"c.cmd": "Core/c.cmd"}),
        ]
        self._register(hub, groups)
        maker = MenuMaker()
        plan = maker.all_roots()
        assert _unique_roots_from_tokens(plan.resolve_tokens()) == ["Core", "Ext"]

    def test_default_priority_is_zero(self):
        import wafer.core.actions.command.menu as _m
        assert getattr(_m.MenuGroup, "PRIORITY", None) == 0
