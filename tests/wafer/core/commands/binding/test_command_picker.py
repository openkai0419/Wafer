import pytest
from unittest.mock import MagicMock
from PySide6 import QtWidgets, QtGui

from wafer.core.commands.command.core import (
    CommandMeta,
    CommandRegistry,
    register_command_defs,
)
from wafer.core.commands.command.menu_builder import CommandMenuBuilder, MenuBuilder
from wafer.core.commands.command.maker import MenuMaker
from wafer.core.commands.command.state import CommandOptionStore
from wafer.core.commands.command.payload import CommandPayload
from wafer.core.commands.binding.editors_common import (
    popup_command_picker,
    ScopedPayloadSectionBase,
)
from wafer.core.commands.binding.common import WidgetRef


PREFIX = "_test_picker_"


def _make_id(name):
    return f"{PREFIX}{name}"


def _cleanup_registry():
    reg = CommandRegistry.instance()
    keys = [k for k in reg._commands if k.startswith(PREFIX)]
    for k in keys:
        del reg._commands[k]


@pytest.fixture(autouse=True)
def _reset_singletons(tmp_path):
    prev_instance = CommandOptionStore._instance
    prev_default = CommandOptionStore._default_path
    CommandOptionStore._instance = None
    CommandOptionStore._default_path = None
    CommandOptionStore.configure(tmp_path / "command_options.json")
    CommandMenuBuilder._menu_cache.clear()
    CommandMenuBuilder._check_states.clear()
    CommandMenuBuilder._action_groups.clear()
    _cleanup_registry()
    yield
    CommandMenuBuilder._menu_cache.clear()
    CommandMenuBuilder._check_states.clear()
    CommandMenuBuilder._action_groups.clear()
    _cleanup_registry()
    CommandOptionStore._instance = prev_instance
    CommandOptionStore._default_path = prev_default


def _register(cmd_id, display, folder="Test"):
    meta = CommandMeta(
        id=cmd_id,
        display=f"{folder}/{display}",
        func=lambda ctx: None,
    )
    register_command_defs([meta])
    return meta


class TestPickerMenuNoCacheWithSelectionCallback:
    def test_selection_callback_returns_fresh_menu_each_time(self, qtbot):
        _register(_make_id("a"), "CmdA")
        parent = QtWidgets.QWidget()
        qtbot.addWidget(parent)
        maker = MenuMaker()
        menus = []
        for _ in range(3):
            builder = MenuBuilder(maker, parent)
            menu = builder.build_all_roots(
                selection_callback=lambda cid: None,
            )
            menus.append(menu)
        assert menus[0] is not menus[1]
        assert menus[1] is not menus[2]

    def test_no_selection_callback_returns_cached_menu(self, qtbot):
        _register(_make_id("b"), "CmdB")
        parent = QtWidgets.QWidget()
        qtbot.addWidget(parent)
        maker = MenuMaker()
        builder1 = MenuBuilder(maker, parent)
        menu1 = builder1.build_all_roots(selection_callback=None)
        builder2 = MenuBuilder(maker, parent)
        menu2 = builder2.build_all_roots(selection_callback=None)
        assert menu1 is menu2


class TestNoneUnsetNotAccumulated:
    def _count_none_actions(self, menu: QtWidgets.QMenu) -> int:
        count = 0
        for action in menu.actions():
            if action.text() and "None" in action.text() and "Unset" in action.text():
                count += 1
        return count

    def test_prepare_does_not_accumulate_none_unset(self, qtbot):
        _register(_make_id("c"), "CmdC")
        parent = QtWidgets.QWidget()
        qtbot.addWidget(parent)

        for i in range(5):
            maker = MenuMaker()
            builder = MenuBuilder(maker, parent)
            menu = builder.build_all_roots(
                selection_callback=lambda cid: None,
            )
            act_none = QtGui.QAction("None (Unset)", menu)
            first = menu.actions()[0] if menu.actions() else None
            if first:
                menu.insertAction(first, act_none)
                menu.insertSeparator(first)
            else:
                menu.addAction(act_none)
            assert self._count_none_actions(menu) == 1, (
                f"iteration {i}: expected 1 'None (Unset)' but found {self._count_none_actions(menu)}"
            )


def _find_command_actions(menu):
    result = []
    for a in menu.actions():
        if a.data():
            result.append(a)
        sub = a.menu()
        if sub is not None:
            result.extend(_find_command_actions(sub))
    return result


class TestScopeCallbackIsolation:
    def test_different_scopes_build_independent_menus(self, qtbot):
        _register(_make_id("d"), "CmdD")
        parent = QtWidgets.QWidget()
        qtbot.addWidget(parent)

        received = []

        def on_select(scope, cid):
            received.append((scope, cid))

        for scope in ["*", "GridView", "ImageView"]:
            maker = MenuMaker()
            builder = MenuBuilder(maker, parent)
            menu = builder.build_all_roots(
                selection_callback=lambda cid, sc=scope: on_select(sc, cid),
            )

            cmd_actions = _find_command_actions(menu)
            if cmd_actions:
                cmd_actions[0].trigger()

        assert len(received) == 3
        assert received[0][0] == "*"
        assert received[1][0] == "GridView"
        assert received[2][0] == "ImageView"

    def test_cached_menu_does_not_carry_old_callback(self, qtbot):
        _register(_make_id("e"), "CmdE")
        parent = QtWidgets.QWidget()
        qtbot.addWidget(parent)

        received_scopes = []

        maker = MenuMaker()

        builder1 = MenuBuilder(maker, parent)
        menu1 = builder1.build_all_roots(
            selection_callback=lambda cid: received_scopes.append("first"),
        )

        builder2 = MenuBuilder(maker, parent)
        menu2 = builder2.build_all_roots(
            selection_callback=lambda cid: received_scopes.append("second"),
        )

        cmd_actions = _find_command_actions(menu2)
        if cmd_actions:
            cmd_actions[0].trigger()

        assert received_scopes == ["second"]


class TestScopedPayloadSectionPickCmd:
    def _make_section(self, qtbot, widgets):
        section = ScopedPayloadSectionBase(
            None,
            widgets,
            header_button_text="Command",
        )
        qtbot.addWidget(section)
        return section

    def test_pick_cmd_global_uses_global_edit(self, qtbot):
        wref = WidgetRef(name="GridView", widget=MagicMock(spec=QtWidgets.QWidget))
        section = self._make_section(qtbot, [wref])
        section._payloads["*"] = CommandPayload("old_cmd", {})
        section.global_edit.setText("old_cmd")

        section._on_select("*", CommandPayload("new_cmd", {}))

        assert section._payloads["*"].id == "new_cmd"
        assert "new_cmd" in section.global_edit.text()

    def test_pick_cmd_override_does_not_modify_global(self, qtbot):
        wref = WidgetRef(name="GridView", widget=MagicMock(spec=QtWidgets.QWidget))
        section = self._make_section(qtbot, [wref])
        section._payloads["*"] = CommandPayload("global_cmd", {})
        section.global_edit.setText("global_cmd")
        section._add_override("GridView")

        section._on_select("GridView", CommandPayload("override_cmd", {}))

        assert section._payloads["*"].id == "global_cmd"
        assert section._payloads["GridView"].id == "override_cmd"
        assert "global_cmd" in section.global_edit.text()

    def test_none_unset_on_global_clears_global(self, qtbot):
        wref = WidgetRef(name="GridView", widget=MagicMock(spec=QtWidgets.QWidget))
        section = self._make_section(qtbot, [wref])
        section._payloads["*"] = CommandPayload("cmd", {})
        section.global_edit.setText("cmd")

        section._on_select("*", None)

        assert "*" not in section._payloads
        assert section.global_edit.text() == ""

    def test_none_unset_on_override_removes_override_row(self, qtbot):
        wref = WidgetRef(name="GridView", widget=MagicMock(spec=QtWidgets.QWidget))
        section = self._make_section(qtbot, [wref])
        section._add_override("GridView")
        section._payloads["GridView"] = CommandPayload("override_cmd", {})

        section._on_select("GridView", None)

        assert "GridView" not in section._payloads
        assert "GridView" not in section.override_edits

    def test_collect_scopes_matches_payloads(self, qtbot):
        wref = WidgetRef(name="GridView", widget=MagicMock(spec=QtWidgets.QWidget))
        section = self._make_section(qtbot, [wref])
        section._payloads["*"] = CommandPayload("global_cmd", {})
        section.global_edit.setText("global_cmd")
        section._add_override("GridView")
        section._payloads["GridView"] = CommandPayload("override_cmd", {})

        scopes = section.collect_scopes()
        assert scopes["*"].id == "global_cmd"
        assert scopes["GridView"].id == "override_cmd"

    def test_override_menu_excludes_existing_overrides(self, qtbot):
        wref1 = WidgetRef(name="GridView", widget=MagicMock(spec=QtWidgets.QWidget))
        wref2 = WidgetRef(name="ImageView", widget=MagicMock(spec=QtWidgets.QWidget))
        section = self._make_section(qtbot, [wref1, wref2])

        section._add_override("GridView")
        section._refresh_overrides_menu()

        menu_texts = [a.text() for a in section.ov_menu.actions()]
        assert "GridView" not in menu_texts
        assert "ImageView" in menu_texts

    def test_override_menu_shows_no_more_when_all_added(self, qtbot):
        wref = WidgetRef(name="GridView", widget=MagicMock(spec=QtWidgets.QWidget))
        section = self._make_section(qtbot, [wref])

        section._add_override("GridView")
        section._refresh_overrides_menu()

        enabled_actions = [a for a in section.ov_menu.actions() if a.isEnabled()]
        assert len(enabled_actions) == 0


class TestMultipleScopedSectionsIndependence:
    def test_two_sections_do_not_share_state(self, qtbot):
        wref = WidgetRef(name="GridView", widget=MagicMock(spec=QtWidgets.QWidget))
        widgets = [wref]
        s1 = ScopedPayloadSectionBase(None, widgets, header_button_text="Cmd")
        s2 = ScopedPayloadSectionBase(None, widgets, header_button_text="Cmd")
        qtbot.addWidget(s1)
        qtbot.addWidget(s2)

        s1._on_select("*", CommandPayload("cmd_a", {}))
        s2._on_select("*", CommandPayload("cmd_b", {}))

        assert s1._payloads["*"].id == "cmd_a"
        assert s2._payloads["*"].id == "cmd_b"
