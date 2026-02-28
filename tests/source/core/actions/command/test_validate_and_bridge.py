import pytest
from unittest.mock import MagicMock

from source.core.actions.command.core import (
    CommandMeta,
    CommandParam,
    CommandRegistry,
    create_command_from_meta,
    register_command_defs,
    validate_command_args,
)
from source.core.actions.command.menu import normalize_command_meta
from source.core.actions.command.state import CommandOptionStore


@pytest.fixture(autouse=True)
def _isolate_registry():
    reg = CommandRegistry()
    prev = dict(reg._commands)
    yield
    reg._commands = prev


@pytest.fixture(autouse=True)
def _isolate_option_store(tmp_path):
    store = CommandOptionStore.configure(tmp_path / "opts.json")
    yield
    store._reconfigure(tmp_path / "opts.json")


def _make_meta(path="test.cmd", params=None, **kw):
    return CommandMeta(path=path, display="Test", params=params or [], func=lambda ctx: "ok", **kw)


def _register(meta):
    normalize_command_meta([], meta)
    register_command_defs([meta])
    return meta


class TestValidateCommandArgs:
    def test_empty_params_empty_args(self):
        meta = _make_meta()
        meta.id = "test.cmd"
        validate_command_args(meta, {}, require_all=True)

    def test_require_all_missing(self):
        meta = _make_meta(params=[CommandParam(name="step", value=1)])
        meta.id = "test.cmd"
        with pytest.raises(ValueError, match="Missing args"):
            validate_command_args(meta, {}, require_all=True)

    def test_require_all_ok(self):
        meta = _make_meta(params=[CommandParam(name="step", value=1)])
        meta.id = "test.cmd"
        validate_command_args(meta, {"step": 5}, require_all=True)

    def test_extra_args(self):
        meta = _make_meta()
        meta.id = "test.cmd"
        with pytest.raises(ValueError, match="Unknown args"):
            validate_command_args(meta, {"bogus": 1})

    def test_type_mismatch(self):
        meta = _make_meta(params=[CommandParam(name="step", value=1)])
        meta.id = "test.cmd"
        with pytest.raises(TypeError, match="expected int"):
            validate_command_args(meta, {"step": "bad"})

    def test_int_accepted_for_float(self):
        meta = _make_meta(params=[CommandParam(name="ratio", value=1.0)])
        meta.id = "test.cmd"
        validate_command_args(meta, {"ratio": 2})

    def test_choices_violation(self):
        meta = _make_meta(params=[CommandParam(name="mode", value=("a", "b"))])
        meta.id = "test.cmd"
        with pytest.raises(ValueError, match="not in"):
            validate_command_args(meta, {"mode": "c"})

    def test_choices_ok(self):
        meta = _make_meta(params=[CommandParam(name="mode", value=("a", "b"))])
        meta.id = "test.cmd"
        validate_command_args(meta, {"mode": "a"})

    def test_min_violation(self):
        meta = _make_meta(params=[CommandParam(name="n", value=10, min_value=0)])
        meta.id = "test.cmd"
        with pytest.raises(ValueError, match="< min"):
            validate_command_args(meta, {"n": -1})

    def test_max_violation(self):
        meta = _make_meta(params=[CommandParam(name="n", value=10, max_value=100)])
        meta.id = "test.cmd"
        with pytest.raises(ValueError, match="> max"):
            validate_command_args(meta, {"n": 200})

    def test_none_value_skips_checks(self):
        meta = _make_meta(params=[CommandParam(name="mode", value=("a", "b"), default=None)])
        meta.id = "test.cmd"
        validate_command_args(meta, {"mode": None})

    def test_partial_ok(self):
        meta = _make_meta(params=[
            CommandParam(name="a", value=1),
            CommandParam(name="b", value=2),
        ])
        meta.id = "test.cmd"
        validate_command_args(meta, {"a": 10})


class TestBridgeCommand:
    def _import_bridge(self):
        from source.core.actions.bridge import Command, Context
        return Command, Context

    def test_run_no_params(self):
        called = {}
        meta = CommandMeta(path="t.nop", display="Nop", func=lambda ctx: called.update(ran=True))
        _register(meta)
        Command, _ = self._import_bridge()
        Command.run("t.nop")
        assert called.get("ran")

    def test_run_with_params(self):
        results = {}
        def fn(ctx, step: int = 1):
            results["step"] = step
        meta = CommandMeta(path="t.stepped", display="S", func=fn, params=[CommandParam(name="step", value=1)])
        _register(meta)
        Command, _ = self._import_bridge()
        Command.run("t.stepped", {"step": 5})
        assert results["step"] == 5

    def test_run_missing_param_raises(self):
        meta = CommandMeta(path="t.req", display="R", func=lambda ctx, x=0: x, params=[CommandParam(name="x", value=0)])
        _register(meta)
        Command, _ = self._import_bridge()
        with pytest.raises(ValueError, match="Missing args"):
            Command.run("t.req", {})

    def test_run_extra_param_raises(self):
        meta = CommandMeta(path="t.nop2", display="N2", func=lambda ctx: None)
        _register(meta)
        Command, _ = self._import_bridge()
        with pytest.raises(ValueError, match="Unknown args"):
            Command.run("t.nop2", {"bogus": 1})

    def test_run_unknown_command_raises(self):
        Command, _ = self._import_bridge()
        with pytest.raises(ValueError, match="Command not found"):
            Command.run("nonexistent.cmd")

    def test_run_type_error(self):
        meta = CommandMeta(path="t.typed", display="T", func=lambda ctx, n=0: n, params=[CommandParam(name="n", value=0)])
        _register(meta)
        Command, _ = self._import_bridge()
        with pytest.raises(TypeError, match="expected int"):
            Command.run("t.typed", {"n": "bad"})

    def test_get_args_defaults(self):
        meta = CommandMeta(
            path="t.defs",
            display="D",
            func=lambda ctx, a=1, b=True: None,
            params=[CommandParam(name="a", value=1), CommandParam(name="b", value=True)],
        )
        _register(meta)
        Command, _ = self._import_bridge()
        assert Command.get_args("t.defs") == {"a": 1, "b": True}

    def test_get_args_unknown_raises(self):
        Command, _ = self._import_bridge()
        with pytest.raises(ValueError, match="Command not found"):
            Command.get_args("nonexistent.cmd")

    def test_get_args_no_params(self):
        meta = CommandMeta(path="t.nop3", display="N3", func=lambda ctx: None)
        _register(meta)
        Command, _ = self._import_bridge()
        assert Command.get_args("t.nop3") == {}

    def test_set_args_and_get_args(self):
        meta = CommandMeta(
            path="t.opts",
            display="O",
            func=lambda ctx, x=1, y=2.0: None,
            params=[CommandParam(name="x", value=1), CommandParam(name="y", value=2.0)],
        )
        _register(meta)
        Command, _ = self._import_bridge()
        Command.set_args("t.opts", {"x": 99})
        result = Command.get_args("t.opts")
        assert result["x"] == 99
        assert result["y"] == 2.0

    def test_set_args_full_overwrite(self):
        meta = CommandMeta(
            path="t.full",
            display="F",
            func=lambda ctx, a=0, b=0: None,
            params=[CommandParam(name="a", value=0), CommandParam(name="b", value=0)],
        )
        _register(meta)
        Command, _ = self._import_bridge()
        Command.set_args("t.full", {"a": 10, "b": 20})
        assert Command.get_args("t.full") == {"a": 10, "b": 20}

    def test_set_args_unknown_command_raises(self):
        Command, _ = self._import_bridge()
        with pytest.raises(ValueError, match="Command not found"):
            Command.set_args("nonexistent.cmd", {"x": 1})

    def test_set_args_extra_key_raises(self):
        meta = CommandMeta(path="t.clean", display="C", func=lambda ctx: None)
        _register(meta)
        Command, _ = self._import_bridge()
        with pytest.raises(ValueError, match="Unknown args"):
            Command.set_args("t.clean", {"nope": 1})

    def test_set_args_type_error(self):
        meta = CommandMeta(
            path="t.typerr",
            display="TE",
            func=lambda ctx, n=0: None,
            params=[CommandParam(name="n", value=0)],
        )
        _register(meta)
        Command, _ = self._import_bridge()
        with pytest.raises(TypeError, match="expected int"):
            Command.set_args("t.typerr", {"n": "bad"})

    def test_set_args_cleans_stale_keys(self):
        meta = CommandMeta(
            path="t.stale",
            display="S",
            func=lambda ctx, a=0: None,
            params=[CommandParam(name="a", value=0)],
        )
        _register(meta)
        Command, _ = self._import_bridge()
        store = CommandOptionStore()
        store.set("t.stale", {"a": 1, "old_removed": 99})
        store.commit()
        Command.set_args("t.stale", {"a": 5})
        result = Command.get_args("t.stale")
        assert result == {"a": 5}

    def test_run_then_get_args_independent(self):
        results = {}
        def fn(ctx, v=0):
            results["v"] = v
        meta = CommandMeta(path="t.indep", display="I", func=fn, params=[CommandParam(name="v", value=0)])
        _register(meta)
        Command, _ = self._import_bridge()
        Command.set_args("t.indep", {"v": 100})
        Command.run("t.indep", {"v": 999})
        assert results["v"] == 999
        assert Command.get_args("t.indep")["v"] == 100

    def test_run_with_extras(self):
        captured = {}
        def fn(ctx):
            captured["foo"] = ctx.get("foo")
            captured["source"] = ctx._info.get("source")
        meta = CommandMeta(path="t.ext", display="E", func=fn)
        _register(meta)
        Command, _ = self._import_bridge()
        Command.run("t.ext", extras={"foo": "bar"})
        assert captured["foo"] == "bar"
        assert captured["source"] == "run"

    def test_run_extras_none(self):
        called = {}
        meta = CommandMeta(path="t.noext", display="NE", func=lambda ctx: called.update(ran=True))
        _register(meta)
        Command, _ = self._import_bridge()
        Command.run("t.noext")
        assert called.get("ran")

    def test_run_drag_command_without_event_raises(self):
        meta = CommandMeta(
            path="t.dragcmd",
            display="Drag",
            category="drag",
            drag_callbacks={"start": lambda ctx: None, "move": lambda ctx: None, "end": lambda ctx: None},
            target_widgets=["TestWidget"],
        )
        _register(meta)
        Command, _ = self._import_bridge()
        with pytest.raises(ValueError, match="requires event"):
            Command.run("t.dragcmd")

    def test_run_drop_command_without_event_raises(self):
        meta = CommandMeta(
            path="t.dropcmd",
            display="Drop",
            category="drop",
            drop_callbacks={"enter": lambda ctx: None, "leave": lambda ctx: None, "drop": lambda ctx: None},
            target_widgets=["TestWidget"],
        )
        _register(meta)
        Command, _ = self._import_bridge()
        with pytest.raises(ValueError, match="requires event"):
            Command.run("t.dropcmd")


class TestCommandContextInfo:
    def test_info_not_accessible_via_get(self):
        from source.core.actions.command.context import CommandContext
        ctx = CommandContext.build(None, "*", source="test")
        assert ctx.get("_info") is None

    def test_info_stores_widget_scope_source(self):
        from source.core.actions.command.context import CommandContext
        widget = object()
        ctx = CommandContext.build(widget, "myscope", source="mouse")
        assert ctx._info["widget"] is widget
        assert ctx._info["scope"] == "myscope"
        assert ctx._info["source"] == "mouse"

    def test_get_public_fields_accessible(self):
        from source.core.actions.command.context import CommandContext
        ctx = CommandContext()
        ctx.wheel_steps = 5
        assert ctx.get("wheel_steps") == 5

    def test_get_event_accessible(self):
        from source.core.actions.command.context import CommandContext
        evt = object()
        ctx = CommandContext()
        ctx.event = evt
        assert ctx.get("event") is evt

    def test_widget_cache_not_accessible_via_get(self):
        from source.core.actions.command.context import CommandContext
        ctx = CommandContext()
        assert ctx.get("_widget_cache") is None

    def test_event_always_set_in_build(self):
        from source.core.actions.command.context import CommandContext
        evt = object()
        ctx = CommandContext.build(None, "*", source="mouse", event=evt)
        assert ctx.event is evt

    def test_event_set_for_drop_source(self):
        from source.core.actions.command.context import CommandContext
        evt = object()
        ctx = CommandContext.build(None, "*", source="drop", event=evt)
        assert ctx.event is evt