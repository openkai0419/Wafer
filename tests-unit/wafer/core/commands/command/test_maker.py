import pytest

from wafer.core.commands.command.menu import MenuHub
from wafer.core.commands.command.maker import MenuMaker
from wafer.core.commands.command.core import CommandMeta


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
            dict(hub._all_paths),
            dict(hub._by_menu),
            dict(hub._menu_items),
            dict(hub._folder_blocks),
            set(hub._folder_set),
            dict(hub._folder_prefix_map),
            list(hub._menu_order),
        )
        hub._all_paths.clear()
        hub._by_menu.clear()
        hub._menu_items.clear()
        hub._folder_blocks.clear()
        hub._folder_set.clear()
        hub._folder_prefix_map.clear()
        hub._menu_order = []
        yield
        hub._all_paths, hub._by_menu, hub._menu_items, hub._folder_blocks, hub._folder_set, hub._folder_prefix_map, hub._menu_order = saved

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

    def test_menu_order_overrides_priority(self):
        hub = MenuHub.instance()
        groups = [
            self._make_group("Ext", 1000, ["Ext/x.cmd"], {"x.cmd": "Ext/x.cmd"}),
            self._make_group("Core", 10, ["Core/c.cmd"], {"c.cmd": "Core/c.cmd"}),
        ]
        self._register(hub, groups)
        hub.set_menu_order(["Ext", "Core"])
        maker = MenuMaker()
        plan = maker.all_roots()
        assert _unique_roots_from_tokens(plan.resolve_tokens()) == ["Ext", "Core"]


def test_unfound_command_returns_unfound_token():
    _register_dummy_menu()
    maker = MenuMaker()
    plan = maker.menu(["t.file.open", "no.such.cmd", "t.file.run"])
    tokens = plan.resolve_tokens()
    assert tokens[0] == "t.file.open"
    assert tokens[1] == "__unfound__:no.such.cmd"
    assert tokens[2] == "t.file.run"


def test_unfound_path_command_returns_unfound_token():
    _register_dummy_menu()
    maker = MenuMaker()
    plan = maker.menu(["some/folder/no.exist"])
    tokens = plan.resolve_tokens()
    assert len(tokens) == 1
    assert tokens[0] == "__unfound__:no.exist"


def test_unfound_does_not_break_other_items():
    _register_dummy_menu()
    maker = MenuMaker()
    plan = maker.menu([":Section", "t.file.open", "missing.cmd", "-", "t.file.run"])
    tokens = plan.resolve_tokens()
    assert ":Section" in tokens
    assert "t.file.open" in tokens
    assert "__unfound__:missing.cmd" in tokens
    assert "-" in tokens
    assert "t.file.run" in tokens

    def test_ordered_items_placed_after_unordered(self):
        hub = MenuHub.instance()
        groups = [
            self._make_group("ExtA", 1000, ["ExtA/a.cmd"], {"a.cmd": "ExtA/a.cmd"}),
            self._make_group("Core", 10, ["Core/c.cmd"], {"c.cmd": "Core/c.cmd"}),
            self._make_group("ExtB", 2000, ["ExtB/b.cmd"], {"b.cmd": "ExtB/b.cmd"}),
        ]
        self._register(hub, groups)
        hub.set_menu_order(["ExtB", "ExtA"])
        maker = MenuMaker()
        plan = maker.all_roots()
        assert _unique_roots_from_tokens(plan.resolve_tokens()) == ["Core", "ExtB", "ExtA"]

    def test_same_name_uses_min_priority(self):
        hub = MenuHub.instance()
        groups = [
            self._make_group("View", 55, ["View/a.cmd"], {"a.cmd": "View/a.cmd"}),
            self._make_group("View", 1200, ["View/b.cmd"], {"b.cmd": "View/b.cmd"}),
            self._make_group("Other", 100, ["Other/o.cmd"], {"o.cmd": "Other/o.cmd"}),
        ]
        self._register(hub, groups)
        maker = MenuMaker()
        plan = maker.all_roots()
        assert _unique_roots_from_tokens(plan.resolve_tokens()) == ["View", "Other"]

    def test_default_priority_is_zero(self):
        import wafer.core.commands.command.menu as _m

        assert getattr(_m.MenuGroup, "PRIORITY", None) == 0
