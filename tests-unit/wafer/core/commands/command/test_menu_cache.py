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
    CommandMenuBuilder._check_states.clear()
    CommandMenuBuilder._action_groups.clear()
    state_mgr = ActionGroupStateManager.instance()
    for k in [k for k in state_mgr._group_members if k.startswith(PREFIX)]:
        del state_mgr._group_members[k]
    for k in [k for k in state_mgr._command_to_group if k.startswith(PREFIX)]:
        del state_mgr._command_to_group[k]
    for k in [k for k in state_mgr._group_defaults if k.startswith(PREFIX)]:
        del state_mgr._group_defaults[k]
    store = CommandOptionStore.instance()
    store._ensure_loaded()
    for k in [k for k in store._map if k.startswith(PREFIX) or k.startswith(f"__group__{PREFIX}")]:
        del store._map[k]
    for k in [k for k in store._buffer if k.startswith(PREFIX) or k.startswith(f"__group__{PREFIX}")]:
        del store._buffer[k]
    _cleanup_registry()
    yield
    CommandMenuBuilder._menu_cache.clear()
    CommandMenuBuilder._check_states.clear()
    CommandMenuBuilder._action_groups.clear()
    for k in [k for k in state_mgr._group_members if k.startswith(PREFIX)]:
        del state_mgr._group_members[k]
    for k in [k for k in state_mgr._command_to_group if k.startswith(PREFIX)]:
        del state_mgr._command_to_group[k]
    for k in [k for k in state_mgr._group_defaults if k.startswith(PREFIX)]:
        del state_mgr._group_defaults[k]
    store._ensure_loaded()
    for k in [k for k in store._map if k.startswith(PREFIX) or k.startswith(f"__group__{PREFIX}")]:
        del store._map[k]
    for k in [k for k in store._buffer if k.startswith(PREFIX) or k.startswith(f"__group__{PREFIX}")]:
        del store._buffer[k]
    _cleanup_registry()
    CommandOptionStore._instance = prev_instance
    CommandOptionStore._default_path = prev_default


def _register_checkable(cmd_id, display, default_checked=False, action_group="", checked_resolver=None):
    meta = CommandMeta(
        id=cmd_id,
        display=display,
        checkable=True,
        default_checked=default_checked,
        action_group=action_group,
        checked_resolver=checked_resolver,
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
            checkable=True,
            default_checked=False,
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

    def test_refresh_updates_check_state(self, qtbot):
        cmd_id = _make_id("chk3")
        _register_checkable(cmd_id, "Check3", default_checked=False)
        w = QtWidgets.QWidget()
        qtbot.addWidget(w)
        builder = CommandMenuBuilder.instance()
        menu = builder.build(w, [cmd_id])
        tracker = menu.property("__checkable_tracker__")
        assert tracker is not None
        widget_action = tracker[0][0]
        assert widget_action.isChecked() is False

        builder._check_states[cmd_id] = True
        builder.refresh_check_states(menu)
        assert widget_action.isChecked() is True

    def test_refresh_updates_checkmark_label(self, qtbot):
        cmd_id = _make_id("chk4")
        _register_checkable(cmd_id, "Check4", default_checked=False)
        w = QtWidgets.QWidget()
        qtbot.addWidget(w)
        builder = CommandMenuBuilder.instance()
        menu = builder.build(w, [cmd_id])
        tracker = menu.property("__checkable_tracker__")
        container = tracker[0][1]
        chk_label = container._chk
        assert chk_label.text() == ""

        builder._check_states[cmd_id] = True
        builder.refresh_check_states(menu)
        assert chk_label.text() == "✓"

    def test_refresh_does_not_trigger_toggled(self, qtbot):
        cmd_id = _make_id("chk5")
        _register_checkable(cmd_id, "Check5", default_checked=False)
        w = QtWidgets.QWidget()
        qtbot.addWidget(w)
        builder = CommandMenuBuilder.instance()
        menu = builder.build(w, [cmd_id])
        toggle_calls = []
        tracker = menu.property("__checkable_tracker__")
        widget_action = tracker[0][0]
        widget_action.toggled.connect(lambda s: toggle_calls.append(s))

        builder._check_states[cmd_id] = True
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
        _register_checkable(a_id, "A", default_checked=True, action_group=gid)
        _register_checkable(b_id, "B", default_checked=False, action_group=gid)
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
        _register_checkable(a_id, "A", default_checked=True, action_group=gid, checked_resolver=lambda: sel["id"] == a_id)
        _register_checkable(b_id, "B", default_checked=False, action_group=gid, checked_resolver=lambda: sel["id"] == b_id)
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
        _register_checkable(cmd_id, "CachedChk", default_checked=False)
        w = QtWidgets.QWidget()
        qtbot.addWidget(w)
        builder = CommandMenuBuilder.instance()
        menu1 = builder.build(w, [cmd_id])
        tracker = menu1.property("__checkable_tracker__")
        wa = tracker[0][0]
        assert wa.isChecked() is False

        CommandMenuBuilder._check_states[cmd_id] = True
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
    def test_toggle_then_refresh_reflects_state(self, qtbot):
        cmd_id = _make_id("tog1")
        _register_checkable(cmd_id, "Toggle1", default_checked=False)
        w = QtWidgets.QWidget()
        qtbot.addWidget(w)
        builder = CommandMenuBuilder.instance()
        menu = builder.build(w, [cmd_id])
        tracker = menu.property("__checkable_tracker__")
        wa = tracker[0][0]
        container = tracker[0][1]
        assert wa.isChecked() is False
        wa.setChecked(True)
        assert builder._check_states.get(cmd_id) is True
        assert container._chk.text() == "✓"
        builder.refresh_check_states(menu)
        assert wa.isChecked() is True
        assert container._chk.text() == "✓"

    def test_toggle_off_then_refresh(self, qtbot):
        cmd_id = _make_id("tog2")
        _register_checkable(cmd_id, "Toggle2", default_checked=True)
        w = QtWidgets.QWidget()
        qtbot.addWidget(w)
        builder = CommandMenuBuilder.instance()
        menu = builder.build(w, [cmd_id])
        tracker = menu.property("__checkable_tracker__")
        wa = tracker[0][0]
        container = tracker[0][1]
        assert wa.isChecked() is True
        wa.setChecked(False)
        assert builder._check_states.get(cmd_id) is False
        builder.refresh_check_states(menu)
        assert wa.isChecked() is False
        assert container._chk.text() == ""

    def test_external_state_change_reflected(self, qtbot):
        cmd_id = _make_id("ext1")
        _register_checkable(cmd_id, "Ext1", default_checked=False)
        w = QtWidgets.QWidget()
        qtbot.addWidget(w)
        builder = CommandMenuBuilder.instance()
        menu = builder.build(w, [cmd_id])
        tracker = menu.property("__checkable_tracker__")
        wa = tracker[0][0]
        container = tracker[0][1]
        assert wa.isChecked() is False

        store = CommandOptionStore.instance()
        store.set(cmd_id, {"checked": True})
        store.commit()

        builder.refresh_check_states(menu)
        assert wa.isChecked() is True
        assert container._chk.text() == "✓"

    def test_group_toggle_via_resolver(self, qtbot):
        gid = _make_id("grp_tog")
        a_id = _make_id("gta")
        b_id = _make_id("gtb")
        sel = {"id": a_id}
        _register_checkable(a_id, "GA", default_checked=True, action_group=gid, checked_resolver=lambda: sel["id"] == a_id)
        _register_checkable(b_id, "GB", default_checked=False, action_group=gid, checked_resolver=lambda: sel["id"] == b_id)
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
    def test_individual_check_stale_after_external_store_change(self, qtbot):
        cmd_id = _make_id("stale1")
        _register_checkable(cmd_id, "Stale1", default_checked=False)
        w = QtWidgets.QWidget()
        qtbot.addWidget(w)
        builder = CommandMenuBuilder.instance()
        menu = builder.build(w, [cmd_id])
        tracker = menu.property("__checkable_tracker__")
        wa = tracker[0][0]
        container = tracker[0][1]

        wa.setChecked(True)
        assert builder._check_states.get(cmd_id) is True

        store = CommandOptionStore.instance()
        store.set(cmd_id, {"checked": False})
        store.commit()

        builder.refresh_check_states(menu)
        assert wa.isChecked() is False, "_check_states shadows CommandOptionStore: external change not reflected"
        assert container._chk.text() == ""

    def test_group_cycle_action_group_reflects(self, qtbot):
        gid = _make_id("cyc_grp")
        a_id = _make_id("cyca")
        b_id = _make_id("cycb")
        sel = {"id": a_id}
        _register_checkable(a_id, "CycA", default_checked=True, action_group=gid, checked_resolver=lambda: sel["id"] == a_id)
        _register_checkable(b_id, "CycB", default_checked=False, action_group=gid, checked_resolver=lambda: sel["id"] == b_id)
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

    def test_individual_external_store_without_prior_toggle(self, qtbot):
        cmd_id = _make_id("ext_no_toggle")
        _register_checkable(cmd_id, "ExtNoTog", default_checked=False)
        w = QtWidgets.QWidget()
        qtbot.addWidget(w)
        builder = CommandMenuBuilder.instance()
        menu = builder.build(w, [cmd_id])
        tracker = menu.property("__checkable_tracker__")
        wa = tracker[0][0]
        assert wa.isChecked() is False

        store = CommandOptionStore.instance()
        store.set(cmd_id, {"checked": True})
        store.commit()

        builder.refresh_check_states(menu)
        assert wa.isChecked() is True


class TestSetCheckedAPI:
    def test_set_checked_updates_check_states_and_store(self, qtbot):
        cmd_id = _make_id("sc1")
        _register_checkable(cmd_id, "SC1", default_checked=False)
        w = QtWidgets.QWidget()
        qtbot.addWidget(w)
        builder = CommandMenuBuilder.instance()
        menu = builder.build(w, [cmd_id])
        tracker = menu.property("__checkable_tracker__")
        wa = tracker[0][0]
        assert wa.isChecked() is False

        builder.set_checked(cmd_id, True)

        assert builder._check_states[cmd_id] is True
        store = CommandOptionStore.instance()
        stored = store.get(cmd_id)
        assert stored.args.get("checked") is True

        builder.refresh_check_states(menu)
        assert wa.isChecked() is True

    def test_set_checked_false_after_toggle(self, qtbot):
        cmd_id = _make_id("sc2")
        _register_checkable(cmd_id, "SC2", default_checked=False)
        w = QtWidgets.QWidget()
        qtbot.addWidget(w)
        builder = CommandMenuBuilder.instance()
        menu = builder.build(w, [cmd_id])
        tracker = menu.property("__checkable_tracker__")
        wa = tracker[0][0]

        wa.setChecked(True)
        assert wa.isChecked() is True

        builder.set_checked(cmd_id, False)

        builder.refresh_check_states(menu)
        assert wa.isChecked() is False

    def test_set_checked_without_menu_build(self, qtbot):
        cmd_id = _make_id("sc3")
        _register_checkable(cmd_id, "SC3", default_checked=False)
        builder = CommandMenuBuilder.instance()
        builder.set_checked(cmd_id, True)
        assert builder._check_states[cmd_id] is True
        store = CommandOptionStore.instance()
        stored = store.get(cmd_id)
        assert stored.args.get("checked") is True

    def test_set_checked_idempotent(self, qtbot):
        cmd_id = _make_id("sc4")
        _register_checkable(cmd_id, "SC4", default_checked=False)
        w = QtWidgets.QWidget()
        qtbot.addWidget(w)
        builder = CommandMenuBuilder.instance()
        menu = builder.build(w, [cmd_id])
        tracker = menu.property("__checkable_tracker__")
        wa = tracker[0][0]

        builder.set_checked(cmd_id, True)
        builder.set_checked(cmd_id, True)

        builder.refresh_check_states(menu)
        assert wa.isChecked() is True
        assert builder._check_states[cmd_id] is True


class TestCheckedResolver:
    def test_resolver_takes_priority_over_store(self, qtbot):
        cmd_id = _make_id("res1")
        state = {"active": True}
        meta = CommandMeta(
            id=cmd_id,
            display="Res1",
            checkable=True,
            default_checked=False,
            checked_resolver=lambda: state["active"],
            func=lambda ctx: None,
        )
        register_command_defs([meta])
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

    def test_resolver_ignores_set_checked(self, qtbot):
        cmd_id = _make_id("res2")
        meta = CommandMeta(
            id=cmd_id,
            display="Res2",
            checkable=True,
            default_checked=False,
            checked_resolver=lambda: False,
            func=lambda ctx: None,
        )
        register_command_defs([meta])
        w = QtWidgets.QWidget()
        qtbot.addWidget(w)
        builder = CommandMenuBuilder.instance()
        builder.set_checked(cmd_id, True)
        menu = builder.build(w, [cmd_id])
        tracker = menu.property("__checkable_tracker__")
        wa = tracker[0][0]
        assert wa.isChecked() is False

    def test_no_resolver_falls_back_to_default(self, qtbot):
        cmd_id = _make_id("res3")
        meta = CommandMeta(
            id=cmd_id,
            display="Res3",
            checkable=True,
            default_checked=True,
            func=lambda ctx: None,
        )
        register_command_defs([meta])
        w = QtWidgets.QWidget()
        qtbot.addWidget(w)
        builder = CommandMenuBuilder.instance()
        menu = builder.build(w, [cmd_id])
        tracker = menu.property("__checkable_tracker__")
        wa = tracker[0][0]
        assert wa.isChecked() is True
