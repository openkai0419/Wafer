import pytest

from wafer.core.commands.command.core import (
    CommandBase,
    CommandMeta,
    CommandParam,
    CommandRegistry,
    validate_command_args,
)
from wafer.core.commands.command.context import CommandContext
from wafer.core.commands.command.state import CommandOptionStore


class TestCommandRegistryFlow:
    def setup_method(self):
        self._orig = CommandRegistry._instance
        CommandRegistry._instance = None

    def teardown_method(self):
        CommandRegistry._instance = self._orig

    def _make_command(self, cmd_id, func=None, params=None, **kwargs):
        class Cmd(CommandBase):
            meta = CommandMeta(
                path=f"test.{cmd_id}",
                id=cmd_id,
                display=cmd_id,
                params=params or [],
                **kwargs,
            )

            def execute(self, **kw):
                if func:
                    return func(**kw)
                return kw

        Cmd.__name__ = f"Cmd_{cmd_id}"
        return Cmd

    def test_register_and_execute(self):
        reg = CommandRegistry.instance()
        results = []
        cmd_cls = self._make_command("test.hello", func=lambda ctx: results.append("executed"))
        reg.register(cmd_cls)

        assert reg.has_command("test.hello")
        ctx = CommandContext.build(source="test")
        reg.execute("test.hello", ctx=ctx)
        assert results == ["executed"]

    def test_execute_unknown_returns_none(self):
        reg = CommandRegistry.instance()
        result = reg.execute("nonexistent", ctx=CommandContext.build())
        assert result is None

    def test_get_command(self):
        reg = CommandRegistry.instance()
        cmd_cls = self._make_command("test.get")
        reg.register(cmd_cls)
        assert reg.get_command("test.get") is cmd_cls
        assert reg.get_command("nope") is None

    def test_overwrite_command(self):
        reg = CommandRegistry.instance()
        results = []
        cmd1 = self._make_command("test.ow", func=lambda ctx: results.append("v1"))
        cmd2 = self._make_command("test.ow", func=lambda ctx: results.append("v2"))
        reg.register(cmd1)
        reg.register(cmd2)
        ctx = CommandContext.build(source="test")
        reg.execute("test.ow", ctx=ctx)
        assert results == ["v2"]

    def test_get_all_commands(self):
        reg = CommandRegistry.instance()
        reg.register(self._make_command("test.a"))
        reg.register(self._make_command("test.b"))
        all_cmds = reg.get_all_commands()
        assert "test.a" in all_cmds
        assert "test.b" in all_cmds

    def test_command_with_params(self):
        reg = CommandRegistry.instance()
        results = []
        params = [CommandParam(name="count", value=1, default=1)]
        cmd_cls = self._make_command(
            "test.param",
            func=lambda ctx, count=1: results.append(count),
            params=params,
        )
        reg.register(cmd_cls)
        ctx = CommandContext.build(source="test")
        reg.execute("test.param", ctx=ctx, count=42)
        assert results == [42]

    def test_category_filtering(self):
        reg = CommandRegistry.instance()
        reg.register(self._make_command("test.cat1", category="edit"))
        reg.register(self._make_command("test.cat2", category="view"))
        reg.register(self._make_command("test.cat3", category="edit"))
        edits = reg.get_commands_by_category("edit")
        assert "test.cat1" in edits
        assert "test.cat3" in edits
        assert "test.cat2" not in edits


class TestValidateCommandArgs:
    def test_valid_args(self):
        meta = CommandMeta(id="t", params=[CommandParam(name="x", value=10)])
        validate_command_args(meta, {"x": 5})

    def test_unknown_arg_raises(self):
        meta = CommandMeta(id="t", params=[CommandParam(name="x", value=10)])
        with pytest.raises(ValueError, match="Unknown args"):
            validate_command_args(meta, {"x": 5, "y": 10})

    def test_missing_required_arg(self):
        meta = CommandMeta(id="t", params=[CommandParam(name="x", value=10)])
        with pytest.raises(ValueError, match="Missing args"):
            validate_command_args(meta, {}, require_all=True)

    def test_type_mismatch_raises(self):
        meta = CommandMeta(id="t", params=[CommandParam(name="x", value=10)])
        with pytest.raises(TypeError, match="expected int"):
            validate_command_args(meta, {"x": "not_int"})

    def test_min_value_violation(self):
        meta = CommandMeta(id="t", params=[CommandParam(name="x", value=10, min_value=0)])
        with pytest.raises(ValueError, match="min"):
            validate_command_args(meta, {"x": -1})

    def test_max_value_violation(self):
        meta = CommandMeta(id="t", params=[CommandParam(name="x", value=10, max_value=100)])
        with pytest.raises(ValueError, match="max"):
            validate_command_args(meta, {"x": 200})


class TestCommandOptionStoreFlow:
    def setup_method(self):
        self._orig_instance = CommandOptionStore._instance
        self._orig_path = CommandOptionStore._default_path
        CommandOptionStore._instance = None
        CommandOptionStore._initialized = False

    def teardown_method(self):
        CommandOptionStore._instance = self._orig_instance
        CommandOptionStore._default_path = self._orig_path

    def test_configure_and_roundtrip(self, tmp_path):
        store_path = tmp_path / "opts.json"
        CommandOptionStore.configure(store_path)
        store = CommandOptionStore.instance()

        store.set("cmd.test", {"mode": "fast", "count": 5})
        store.commit()

        CommandOptionStore._instance = None
        CommandOptionStore._initialized = False
        CommandOptionStore.configure(store_path)
        store2 = CommandOptionStore.instance()
        payload = store2.get("cmd.test")
        assert payload.args["mode"] == "fast"
        assert payload.args["count"] == 5

    def test_get_nonexistent_returns_empty(self, tmp_path):
        CommandOptionStore.configure(tmp_path / "opts.json")
        store = CommandOptionStore.instance()
        payload = store.get("nonexistent")
        assert payload.args == {}
