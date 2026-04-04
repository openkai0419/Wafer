import pytest
from unittest.mock import MagicMock

from wafer.core.commands.command.core import (
    CommandMeta,
    CommandParam,
    CommandRegistry,
    CommandBase,
    DropAcceptRegistry,
    create_command_from_meta,
    register_command_defs,
    validate_command_args,
    _build_args,
    call_with_matching_args,
)
from wafer.core.commands.command.context import CommandContext
from wafer.core.commands.command.state import CommandOptionStore, ActionGroupStateManager


@pytest.fixture(autouse=True)
def _isolate_registry():
    reg = CommandRegistry.instance()
    prev = dict(reg._commands)
    yield
    reg._commands = prev


@pytest.fixture(autouse=True)
def _isolate_drop_accept():
    dar = DropAcceptRegistry.instance()
    prev = {k: list(v) for k, v in dar._acceptors.items()}
    dar._acceptors = {}
    yield
    dar._acceptors = prev


@pytest.fixture(autouse=True)
def _isolate_option_store(tmp_path):
    prev_inst = CommandOptionStore._instance
    prev_path = CommandOptionStore._default_path
    CommandOptionStore._instance = None
    CommandOptionStore.configure(tmp_path / "opts.json")
    yield
    CommandOptionStore._instance = prev_inst
    CommandOptionStore._default_path = prev_path


@pytest.fixture(autouse=True)
def _isolate_state_manager():
    prev = ActionGroupStateManager._instance
    ActionGroupStateManager._instance = None
    yield
    ActionGroupStateManager._instance = prev


class TestDropAcceptRegistry:
    def test_register_and_resolve(self):
        acceptor = lambda event: True
        DropAcceptRegistry.instance().register("GridView", acceptor)
        result = DropAcceptRegistry.instance().resolve("GridView")
        assert acceptor in result

    def test_resolve_falls_back_to_global(self):
        acceptor = lambda event: True
        DropAcceptRegistry.instance().register("*", acceptor)
        result = DropAcceptRegistry.instance().resolve("GridView")
        assert acceptor in result

    def test_resolve_widget_specific_before_global(self):
        a1 = lambda event: True
        a2 = lambda event: False
        dar = DropAcceptRegistry.instance()
        dar.register("GridView", a1)
        dar.register("*", a2)
        result = dar.resolve("GridView")
        assert list(result).index(a1) < list(result).index(a2)

    def test_resolve_global_only(self):
        a = lambda event: True
        DropAcceptRegistry.instance().register("*", a)
        result = DropAcceptRegistry.instance().resolve("*")
        assert a in result

    def test_resolve_empty(self):
        result = DropAcceptRegistry.instance().resolve("Unknown")
        assert len(result) == 0

    def test_resolve_none_scope_falls_to_global(self):
        a = lambda event: True
        DropAcceptRegistry.instance().register("*", a)
        result = DropAcceptRegistry.instance().resolve(None)
        assert a in result

    def test_register_duplicate_ignored(self):
        a = lambda event: True
        dar = DropAcceptRegistry.instance()
        dar.register("GridView", a)
        dar.register("GridView", a)
        result = dar.resolve("GridView")
        assert len(result) == 1

    def test_register_empty_scope_raises(self):
        with pytest.raises(ValueError, match="widget_scope is required"):
            DropAcceptRegistry.instance().register("", lambda e: True)

    def test_register_non_callable_raises(self):
        with pytest.raises(ValueError, match="acceptor must be callable"):
            DropAcceptRegistry.instance().register("GridView", "not callable")

    def test_no_duplicates_in_merged_result(self):
        a = lambda event: True
        dar = DropAcceptRegistry.instance()
        dar.register("GridView", a)
        dar.register("*", a)
        result = dar.resolve("GridView")
        assert len(result) == 1


class TestRegisterCommandDefs:
    def test_register_basic_command(self):
        meta = CommandMeta(id="test.basic", display="Basic", func=lambda ctx: "ok")
        register_command_defs([meta])
        assert CommandRegistry.instance().has_command("test.basic")

    def test_drag_category_without_callbacks_raises(self):
        meta = CommandMeta(id="test.drag_bad", display="Bad", category="drag", func=lambda ctx: None)
        with pytest.raises(ValueError, match="missing drag_callbacks"):
            register_command_defs([meta])

    def test_drop_category_without_callbacks_raises(self):
        meta = CommandMeta(id="test.drop_bad", display="Bad", category="drop", func=lambda ctx: None)
        with pytest.raises(ValueError, match="missing drop_callbacks"):
            register_command_defs([meta])

    def test_drag_with_func_raises(self):
        meta = CommandMeta(
            id="test.drag_func", display="Bad", category="drag",
            drag_callbacks={"start": lambda ctx: None},
            func=lambda ctx: None,
        )
        with pytest.raises(ValueError, match="uses func"):
            register_command_defs([meta])

    def test_drop_with_func_raises(self):
        meta = CommandMeta(
            id="test.drop_func", display="Bad", category="drop",
            drop_callbacks={"drop": lambda ctx: None},
            func=lambda ctx: None,
        )
        with pytest.raises(ValueError, match="uses func"):
            register_command_defs([meta])

    def test_drag_with_callbacks_ok(self):
        meta = CommandMeta(
            id="test.drag_ok", display="Drag", category="drag",
            drag_callbacks={"start": lambda ctx: None, "move": lambda ctx: None},
        )
        register_command_defs([meta])
        assert CommandRegistry.instance().has_command("test.drag_ok")

    def test_drop_with_callbacks_ok(self):
        meta = CommandMeta(
            id="test.drop_ok", display="Drop", category="drop",
            drop_callbacks={"drop": lambda ctx: None},
        )
        register_command_defs([meta])
        assert CommandRegistry.instance().has_command("test.drop_ok")

    def test_action_group_registered(self):
        meta = CommandMeta(
            id="test.grp_member", display="Member",
            action_group="test_group", checkable=True,
            func=lambda ctx: None,
        )
        register_command_defs([meta])
        mgr = ActionGroupStateManager.instance()
        assert "test.grp_member" in mgr.get_members("test_group")

    def test_action_group_not_registered_without_checkable(self):
        meta = CommandMeta(
            id="test.grp_nochk", display="NoCheck",
            action_group="test_group", checkable=False,
            func=lambda ctx: None,
        )
        register_command_defs([meta])
        mgr = ActionGroupStateManager.instance()
        assert "test.grp_nochk" not in mgr.get_members("test_group")

    def test_drop_acceptor_registered(self):
        acceptor = lambda event: True
        meta = CommandMeta(
            id="test.drop_acc", display="DropAcc", category="drop",
            drop_callbacks={"drop": lambda ctx: None},
            drop_acceptor=acceptor, target_widgets=["GridView"],
        )
        register_command_defs([meta])
        result = DropAcceptRegistry.instance().resolve("GridView")
        assert acceptor in result

    def test_drop_acceptor_no_target_uses_global(self):
        acceptor = lambda event: True
        meta = CommandMeta(
            id="test.drop_glob", display="DropGlob", category="drop",
            drop_callbacks={"drop": lambda ctx: None},
            drop_acceptor=acceptor,
        )
        register_command_defs([meta])
        result = DropAcceptRegistry.instance().resolve("*")
        assert acceptor in result


class TestCallWithMatchingArgs:
    def test_basic_call(self):
        def fn(a, b):
            return a + b
        assert call_with_matching_args(fn, {"a": 1, "b": 2}) == 3

    def test_ignores_extra_args(self):
        def fn(a):
            return a
        assert call_with_matching_args(fn, {"a": 1, "extra": 99}) == 1

    def test_with_kwargs(self):
        def fn(a, **kwargs):
            return (a, kwargs)
        result = call_with_matching_args(fn, {"a": 1, "b": 2, "c": 3})
        assert result[0] == 1
        assert result[1] == {"b": 2, "c": 3}

    def test_with_defaults(self):
        def fn(a, b=10):
            return a + b
        assert call_with_matching_args(fn, {"a": 5}) == 15

    def test_none_values(self):
        assert call_with_matching_args(lambda: 42, None) == 42

    def test_empty_values(self):
        assert call_with_matching_args(lambda: 42, {}) == 42


class TestBuildArgs:
    def test_basic(self):
        meta = CommandMeta(id="test.cmd", params=[CommandParam(name="step", value=1)])
        ctx = MagicMock()
        result = _build_args(meta, {"step": 5, "ctx": ctx})
        assert result["step"] == 5
        assert result["ctx"] is ctx

    def test_defaults_used_for_missing(self):
        meta = CommandMeta(id="test.cmd", params=[CommandParam(name="step", value=10)])
        ctx = MagicMock()
        result = _build_args(meta, {"ctx": ctx})
        assert result["step"] == 10

    def test_missing_ctx_raises(self):
        meta = CommandMeta(id="test.cmd", params=[])
        with pytest.raises(ValueError, match="ctx is required"):
            _build_args(meta, {})


class TestCreateCommandFromMeta:
    def test_func_creates_executable_command(self):
        results = []
        meta = CommandMeta(id="test.f", display="F", func=lambda ctx: results.append("called"))
        cls = create_command_from_meta(meta)
        assert issubclass(cls, CommandBase)
        cmd = cls()
        cmd.execute(ctx=MagicMock())
        assert results == ["called"]

    def test_drag_callbacks_dispatched(self):
        results = []
        meta = CommandMeta(
            id="test.drag_cb", display="Drag", category="drag",
            drag_callbacks={"start": lambda ctx: results.append("start")},
        )
        cls = create_command_from_meta(meta)
        cmd = cls()
        ctx = MagicMock()
        ctx.get.return_value = "start"
        cmd.execute(ctx=ctx)
        assert results == ["start"]

    def test_drag_callbacks_unknown_phase(self):
        meta = CommandMeta(
            id="test.drag_unk", display="Drag", category="drag",
            drag_callbacks={"start": lambda ctx: None},
        )
        cls = create_command_from_meta(meta)
        cmd = cls()
        ctx = MagicMock()
        ctx.get.return_value = "unknown_phase"
        result = cmd.execute(ctx=ctx)
        assert result is None

    def test_drag_callbacks_no_phase(self):
        meta = CommandMeta(
            id="test.drag_nophase", display="Drag", category="drag",
            drag_callbacks={"start": lambda ctx: None},
        )
        cls = create_command_from_meta(meta)
        cmd = cls()
        ctx = MagicMock()
        ctx.get.return_value = None
        result = cmd.execute(ctx=ctx)
        assert result is None


class TestCommandMetaValidation:
    def test_hotkey_raises(self):
        with pytest.raises(ValueError, match="hotkey must not be set"):
            CommandMeta(id="test.hk", hotkey="Ctrl+C")

    def test_has_options_true_when_params(self):
        meta = CommandMeta(id="test.opts", params=[CommandParam(name="x", value=1)])
        assert meta.has_options is True

    def test_has_options_false_no_params(self):
        meta = CommandMeta(id="test.nopts")
        assert meta.has_options is False


class TestCommandRegistryCategories:
    def test_get_all_categories(self):
        reg = CommandRegistry.instance()
        m1 = CommandMeta(id="test.cat1", category="view", func=lambda ctx: None)
        m2 = CommandMeta(id="test.cat2", category="edit", func=lambda ctx: None)
        reg.register(create_command_from_meta(m1))
        reg.register(create_command_from_meta(m2))
        cats = reg.get_all_categories()
        assert "view" in cats
        assert "edit" in cats

    def test_get_commands_by_category_no_target(self):
        reg = CommandRegistry.instance()
        m = CommandMeta(id="test.catcmd", category="tools", func=lambda ctx: None)
        reg.register(create_command_from_meta(m))
        result = reg.get_commands_by_category("tools")
        assert "test.catcmd" in result

    def test_get_commands_by_category_with_target(self):
        reg = CommandRegistry.instance()
        m = CommandMeta(id="test.targeted", category="tools", func=lambda ctx: None, target_widgets=["GridView"])
        reg.register(create_command_from_meta(m))
        result = reg.get_commands_by_category("tools", widget_scope="GridView")
        assert "test.targeted" in result

    def test_get_commands_by_category_wrong_scope(self):
        reg = CommandRegistry.instance()
        m = CommandMeta(id="test.wrong_scope", category="tools", func=lambda ctx: None, target_widgets=["GridView"])
        reg.register(create_command_from_meta(m))
        result = reg.get_commands_by_category("tools", widget_scope="ImageView")
        assert "test.wrong_scope" not in result

    def test_get_commands_empty_category(self):
        reg = CommandRegistry.instance()
        result = reg.get_commands_by_category("nonexistent")
        assert result == {}


class TestCommandParamEdgeCases:
    def test_empty_name_raises(self):
        with pytest.raises(ValueError, match="name is required"):
            CommandParam(name="", value=1)

    def test_empty_choices_raises(self):
        with pytest.raises(ValueError, match="must not be empty"):
            CommandParam(name="x", value=[])

    def test_callable_value_sets_choices_fn(self):
        fn = lambda: ["a", "b"]
        p = CommandParam(name="mode", value=fn, default="a")
        assert p.choices_fn is fn
        assert p.choices is None
        assert p.resolve_choices() == ["a", "b"]

    def test_list_value_sets_static_choices(self):
        p = CommandParam(name="mode", value=["a", "b", "c"])
        assert p.choices == ["a", "b", "c"]
        assert p.choices_fn is None
        assert p.resolve_choices() == ["a", "b", "c"]

    def test_scalar_value_no_choices(self):
        p = CommandParam(name="step", value=5)
        assert p.choices is None
        assert p.choices_fn is None
        assert p.resolve_choices() is None

    def test_type_class_not_treated_as_callable(self):
        p = CommandParam(name="x", value=int)
        assert p.choices_fn is None

    def test_required_default_false(self):
        p = CommandParam(name="x", value=1)
        assert p.required is False

    def test_required_explicit_true(self):
        p = CommandParam(name="x", value=1, required=True)
        assert p.required is True

    def test_min_max_stored(self):
        p = CommandParam(name="x", value=50, min_value=0, max_value=100)
        assert p.min_value == 0
        assert p.max_value == 100

    def test_explicit_default_with_list(self):
        p = CommandParam(name="mode", value=["a", "b"], default="b")
        assert p.default == "b"

    def test_default_is_first_choice(self):
        p = CommandParam(name="mode", value=["x", "y"])
        assert p.default == "x"


class TestValidateCommandArgsEdgeCases:
    def test_none_value_skips_type_check(self):
        meta = CommandMeta(id="test.none", params=[CommandParam(name="step", value=1)])
        validate_command_args(meta, {"step": None})

    def test_none_value_skips_choices_check(self):
        meta = CommandMeta(id="test.none_ch", params=[CommandParam(name="mode", value=["a", "b"])])
        validate_command_args(meta, {"mode": None})

    def test_none_value_skips_range_check(self):
        meta = CommandMeta(id="test.none_rng", params=[CommandParam(name="x", value=50, min_value=0, max_value=100)])
        validate_command_args(meta, {"x": None})

    def test_partial_ok_without_require_all(self):
        meta = CommandMeta(id="test.partial", params=[
            CommandParam(name="a", value=1),
            CommandParam(name="b", value=2),
        ])
        validate_command_args(meta, {"a": 5})

    def test_dynamic_choices_skip_validation(self):
        p = CommandParam(name="mode", value=lambda: ["a", "b"])
        meta = CommandMeta(id="test.dyn", params=[p])
        validate_command_args(meta, {"mode": "c"})
