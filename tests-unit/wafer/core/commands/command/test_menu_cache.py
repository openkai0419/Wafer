import pytest
from PySide6 import QtWidgets, QtGui

from wafer.core.commands.command.core import (
    CommandBase,
    CommandMeta,
    CommandRegistry,
    MenuAction,
    register_command_defs,
)
from wafer.core.commands.command.menu_builder import CommandMenuBuilder, MenuBuilder
from wafer.core.commands.command.maker import MenuMaker
from wafer.core.commands.command.state import ActionGroupStateManager, CommandOptionStore
from wafer.core.lang.manager import translator


PREFIX = "_test_cache_"


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
    CommandMenuBuilder._action_groups.clear()
    state_mgr = ActionGroupStateManager.instance()
    for k in [k for k in state_mgr._group_members if k.startswith(PREFIX)]:
        del state_mgr._group_members[k]
    for k in [k for k in state_mgr._command_to_group if k.startswith(PREFIX)]:
        del state_mgr._command_to_group[k]
    store = CommandOptionStore.instance()
    store._ensure_loaded()
    for k in [k for k in store._map if k.startswith(PREFIX) or k.startswith(f"__group__{PREFIX}")]:
        del store._map[k]
    for k in [k for k in store._buffer if k.startswith(PREFIX) or k.startswith(f"__group__{PREFIX}")]:
        del store._buffer[k]
    _cleanup_registry()
    yield
    CommandMenuBuilder._menu_cache.clear()
    CommandMenuBuilder._action_groups.clear()
    for k in [k for k in state_mgr._group_members if k.startswith(PREFIX)]:
        del state_mgr._group_members[k]
    for k in [k for k in state_mgr._command_to_group if k.startswith(PREFIX)]:
        del state_mgr._command_to_group[k]
    store._ensure_loaded()
    for k in [k for k in store._map if k.startswith(PREFIX) or k.startswith(f"__group__{PREFIX}")]:
        del store._map[k]
    for k in [k for k in store._buffer if k.startswith(PREFIX) or k.startswith(f"__group__{PREFIX}")]:
        del store._buffer[k]
    _cleanup_registry()
    CommandOptionStore._instance = prev_instance
    CommandOptionStore._default_path = prev_default


def _register_checkable(cmd_id, display, checked=None, action_group=""):
    meta = CommandMeta(
        id=cmd_id,
        display=display,
        checked=checked if checked is not None else (lambda: False),
        action_group=action_group,
        func=lambda ctx: None,
    )
    register_command_defs([meta])
    return meta


def _register_normal(cmd_id, display):
    meta = CommandMeta(
        id=cmd_id,
        display=display,
        func=lambda ctx: None,
    )
    register_command_defs([meta])
    return meta


class TestTransientMenuAction:
    def test_action_can_skip_display_translation(self, qtbot):
        w = QtWidgets.QWidget()
        qtbot.addWidget(w)
        maker = MenuMaker()
        dynamic_display = 'Remove "sample.png"'
        action = MenuAction(
            path=_make_id("raw_display_action"),
            display=dynamic_display,
            translate=False,
            func=lambda ctx: None,
        )

        before = set(translator.missing_keys)
        menu = MenuBuilder(maker, w).build(maker.menu([action]))
        row = menu.actions()[0].defaultWidget()

        assert row._tl.text() == dynamic_display
        assert translator.missing_keys == before

    def test_action_executes_without_global_registration_or_menu_cache(self, qtbot):
        reg = CommandRegistry.instance()
        before = set(reg._commands)
        calls = []
        w = QtWidgets.QWidget()
        qtbot.addWidget(w)

        for i in range(3):
            maker = MenuMaker()
            action = MenuAction(
                path=_make_id(f"action_{i}"),
                display=f"Action {i}",
                func=lambda ctx, n=i: calls.append(n),
            )
            menu = MenuBuilder(maker, w).build(maker.menu([action]))
            menu.actions()[0].trigger()

        assert calls == [0, 1, 2]
        assert set(reg._commands) == before
        assert CommandMenuBuilder._menu_cache == {}

    def test_checkable_action_passes_menu_checked_state(self, qtbot):
        values = []
        w = QtWidgets.QWidget()
        qtbot.addWidget(w)
        maker = MenuMaker()
        action = MenuAction(
            path=_make_id("checked_action"),
            display="Checked Action",
            checked=lambda: False,
            func=lambda ctx: values.append(ctx.get("checked")),
        )

        menu = MenuBuilder(maker, w).build(maker.menu([action]))
        act = menu.actions()[0]
        assert act.isCheckable()
        assert not act.isChecked()
        act.trigger()

        assert values == [True]


class TestRefreshCheckStatesIndividual:
    def test_tracker_stored_on_menu(self, qtbot):
        _register_checkable(_make_id("chk1"), "Check1")
        w = QtWidgets.QWidget()
        qtbot.addWidget(w)
        builder = CommandMenuBuilder.instance()
        menu = builder.build(w, [_make_id("chk1")])
        tracker = menu.property("__checkable_tracker__")
        assert tracker is not None
        assert len(tracker) == 1

    def test_tracker_not_none_after_build_into(self, qtbot):
        _register_checkable(_make_id("chk2"), "Check2")
        w = QtWidgets.QWidget()
        qtbot.addWidget(w)
        builder = CommandMenuBuilder.instance()
        menu = QtWidgets.QMenu(w)
        builder.build_into(menu, w, [_make_id("chk2")])
        tracker = menu.property("__checkable_tracker__")
        assert tracker is not None
        assert len(tracker) == 1

    def test_refresh_reflects_resolver_change(self, qtbot):
        cmd_id = _make_id("chk3")
        state = {"on": False}
        _register_checkable(cmd_id, "Check3", checked=lambda: state["on"])
        w = QtWidgets.QWidget()
        qtbot.addWidget(w)
        builder = CommandMenuBuilder.instance()
        menu = builder.build(w, [cmd_id])
        tracker = menu.property("__checkable_tracker__")
        widget_action = tracker[0][0]
        container = tracker[0][1]
        assert widget_action.isChecked() is False
        assert container._chk.text() == ""

        state["on"] = True
        builder.refresh_check_states(menu)
        assert widget_action.isChecked() is True
        assert container._chk.text() == "✓"

    def test_refresh_does_not_trigger_toggled(self, qtbot):
        cmd_id = _make_id("chk5")
        state = {"on": False}
        _register_checkable(cmd_id, "Check5", checked=lambda: state["on"])
        w = QtWidgets.QWidget()
        qtbot.addWidget(w)
        builder = CommandMenuBuilder.instance()
        menu = builder.build(w, [cmd_id])
        toggle_calls = []
        tracker = menu.property("__checkable_tracker__")
        widget_action = tracker[0][0]
        widget_action.toggled.connect(lambda s: toggle_calls.append(s))

        state["on"] = True
        builder.refresh_check_states(menu)
        assert toggle_calls == []

    def test_normal_command_has_no_tracker_entry(self, qtbot):
        cmd_id = _make_id("norm1")
        _register_normal(cmd_id, "Normal1")
        w = QtWidgets.QWidget()
        qtbot.addWidget(w)
        builder = CommandMenuBuilder.instance()
        menu = builder.build(w, [cmd_id])
        tracker = menu.property("__checkable_tracker__")
        assert tracker == []


class TestRefreshCheckStatesGroup:
    def test_group_initial_default(self, qtbot):
        gid = _make_id("grp")
        a_id = _make_id("ga")
        b_id = _make_id("gb")
        sel = {"id": a_id}
        _register_checkable(a_id, "A", action_group=gid, checked=lambda: sel["id"] == a_id)
        _register_checkable(b_id, "B", action_group=gid, checked=lambda: sel["id"] == b_id)
        w = QtWidgets.QWidget()
        qtbot.addWidget(w)
        builder = CommandMenuBuilder.instance()
        menu = builder.build(w, [a_id, b_id])
        tracker = menu.property("__checkable_tracker__")
        assert len(tracker) == 2
        wa_a = tracker[0][0]
        wa_b = tracker[1][0]
        assert wa_a.isChecked() is True
        assert wa_b.isChecked() is False

    def test_group_refresh_after_state_change(self, qtbot):
        gid = _make_id("grp2")
        a_id = _make_id("g2a")
        b_id = _make_id("g2b")
        sel = {"id": a_id}
        _register_checkable(a_id, "A", action_group=gid, checked=lambda: sel["id"] == a_id)
        _register_checkable(b_id, "B", action_group=gid, checked=lambda: sel["id"] == b_id)
        w = QtWidgets.QWidget()
        qtbot.addWidget(w)
        builder = CommandMenuBuilder.instance()
        menu = builder.build(w, [a_id, b_id])
        tracker = menu.property("__checkable_tracker__")
        wa_a = tracker[0][0]
        wa_b = tracker[1][0]
        assert wa_a.isChecked() is True
        assert wa_b.isChecked() is False

        sel["id"] = b_id

        builder.refresh_check_states(menu)
        assert wa_a.isChecked() is False
        assert wa_b.isChecked() is True


class TestMenuBuilderCache:
    def test_cache_refreshes_check_state(self, qtbot):
        cmd_id = _make_id("cached_chk")
        state = {"on": False}
        _register_checkable(cmd_id, "CachedChk", checked=lambda: state["on"])
        w = QtWidgets.QWidget()
        qtbot.addWidget(w)
        builder = CommandMenuBuilder.instance()
        menu1 = builder.build(w, [cmd_id])
        tracker = menu1.property("__checkable_tracker__")
        wa = tracker[0][0]
        assert wa.isChecked() is False

        state["on"] = True
        builder.refresh_check_states(menu1)
        assert wa.isChecked() is True

    def test_cache_key_includes_parent(self, qtbot):
        cmd_id = _make_id("par1")
        _register_normal(cmd_id, "Par1")
        w1 = QtWidgets.QWidget()
        w2 = QtWidgets.QWidget()
        qtbot.addWidget(w1)
        qtbot.addWidget(w2)
        builder = CommandMenuBuilder.instance()
        menu1 = builder.build(w1, [cmd_id])
        menu2 = builder.build(w2, [cmd_id])
        assert menu1 is not menu2


class TestToggleThenRefresh:
    def test_group_toggle_via_resolver(self, qtbot):
        gid = _make_id("grp_tog")
        a_id = _make_id("gta")
        b_id = _make_id("gtb")
        sel = {"id": a_id}
        _register_checkable(a_id, "GA", action_group=gid, checked=lambda: sel["id"] == a_id)
        _register_checkable(b_id, "GB", action_group=gid, checked=lambda: sel["id"] == b_id)
        w = QtWidgets.QWidget()
        qtbot.addWidget(w)
        builder = CommandMenuBuilder.instance()
        menu = builder.build(w, [a_id, b_id])
        tracker = menu.property("__checkable_tracker__")
        wa_a = tracker[0][0]
        wa_b = tracker[1][0]
        assert wa_a.isChecked() is True
        assert wa_b.isChecked() is False

        sel["id"] = b_id

        builder.refresh_check_states(menu)
        assert wa_a.isChecked() is False
        assert wa_b.isChecked() is True


class TestExternalStateChangeBugs:
    def test_group_cycle_action_group_reflects(self, qtbot):
        gid = _make_id("cyc_grp")
        a_id = _make_id("cyca")
        b_id = _make_id("cycb")
        sel = {"id": a_id}
        _register_checkable(a_id, "CycA", action_group=gid, checked=lambda: sel["id"] == a_id)
        _register_checkable(b_id, "CycB", action_group=gid, checked=lambda: sel["id"] == b_id)
        w = QtWidgets.QWidget()
        qtbot.addWidget(w)
        builder = CommandMenuBuilder.instance()
        menu = builder.build(w, [a_id, b_id])
        tracker = menu.property("__checkable_tracker__")
        wa_a = tracker[0][0]
        wa_b = tracker[1][0]
        assert wa_a.isChecked() is True
        assert wa_b.isChecked() is False

        sel["id"] = b_id
        builder.cycle_action_group(gid)

        builder.refresh_check_states(menu)
        assert wa_a.isChecked() is False, "After cycle, old item should be unchecked"
        assert wa_b.isChecked() is True, "After cycle, new item should be checked"


class TestCheckedResolver:
    def test_resolver_drives_checkmark(self, qtbot):
        cmd_id = _make_id("res1")
        state = {"active": True}
        _register_checkable(cmd_id, "Res1", checked=lambda: state["active"])
        w = QtWidgets.QWidget()
        qtbot.addWidget(w)
        builder = CommandMenuBuilder.instance()
        menu = builder.build(w, [cmd_id])
        tracker = menu.property("__checkable_tracker__")
        wa = tracker[0][0]
        assert wa.isChecked() is True

        state["active"] = False
        builder.refresh_check_states(menu)
        assert wa.isChecked() is False
