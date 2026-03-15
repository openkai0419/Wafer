import pytest
from unittest.mock import MagicMock, patch
from wafer.core.commands.command.core import (
    CommandRegistry, CommandMeta, CommandBase, create_command_from_meta,
)


@pytest.fixture()
def clean_registry():
    registry = CommandRegistry.instance()
    prev = dict(registry._commands)
    registry._commands = {}
    yield registry
    registry._commands = prev


class TestCommandRegistryMissingCommand:
    def test_execute_returns_none_for_missing(self, clean_registry):
        result = clean_registry.execute("nonexistent_cmd", ctx=MagicMock())
        assert result is None

    def test_execute_logs_warning_for_missing(self, clean_registry):
        with patch("wafer.core.commands.command.core.AppLogger") as mock_log:
            clean_registry.execute("nonexistent_cmd", ctx=MagicMock())
            mock_log.warning.assert_called_once()
            assert "nonexistent_cmd" in mock_log.warning.call_args[0][0]


class TestCommandRegistryPriority:
    def test_register_same_id_higher_priority_overrides(self, clean_registry):
        meta_low = CommandMeta(id="test.cmd", display="Low", priority=10, func=lambda ctx: "low")
        meta_high = CommandMeta(id="test.cmd", display="High", priority=20, func=lambda ctx: "high")
        clean_registry.register(create_command_from_meta(meta_low))
        clean_registry.register(create_command_from_meta(meta_high))
        cmd_cls = clean_registry.get_command("test.cmd")
        assert cmd_cls.meta.display == "High"

    def test_register_same_id_lower_priority_ignored(self, clean_registry):
        meta_high = CommandMeta(id="test.cmd", display="High", priority=20, func=lambda ctx: "high")
        meta_low = CommandMeta(id="test.cmd", display="Low", priority=10, func=lambda ctx: "low")
        clean_registry.register(create_command_from_meta(meta_high))
        clean_registry.register(create_command_from_meta(meta_low))
        cmd_cls = clean_registry.get_command("test.cmd")
        assert cmd_cls.meta.display == "High"

    def test_register_same_id_equal_priority_overrides(self, clean_registry):
        meta_a = CommandMeta(id="test.cmd", display="A", priority=10, func=lambda ctx: "a")
        meta_b = CommandMeta(id="test.cmd", display="B", priority=10, func=lambda ctx: "b")
        clean_registry.register(create_command_from_meta(meta_a))
        clean_registry.register(create_command_from_meta(meta_b))
        cmd_cls = clean_registry.get_command("test.cmd")
        assert cmd_cls.meta.display == "B"

    def test_register_same_id_default_priority_overrides(self, clean_registry):
        meta_a = CommandMeta(id="test.cmd", display="A", func=lambda ctx: "a")
        meta_b = CommandMeta(id="test.cmd", display="B", func=lambda ctx: "b")
        clean_registry.register(create_command_from_meta(meta_a))
        clean_registry.register(create_command_from_meta(meta_b))
        cmd_cls = clean_registry.get_command("test.cmd")
        assert cmd_cls.meta.display == "B"


class TestCommandMetaPriority:
    def test_default_priority_is_zero(self):
        meta = CommandMeta(id="x", display="x")
        assert meta.priority == 0

    def test_priority_set_explicitly(self):
        meta = CommandMeta(id="x", display="x", priority=50)
        assert meta.priority == 50
