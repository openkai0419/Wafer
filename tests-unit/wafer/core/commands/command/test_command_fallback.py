import pytest
from unittest.mock import MagicMock, patch
from wafer.core.commands.command.core import (
    CommandRegistry,
    CommandMeta,
    CommandBase,
    create_command_from_meta,
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


class TestCommandRegistryOverride:
    def test_register_same_id_last_wins(self, clean_registry):
        meta_a = CommandMeta(id="test.cmd", display="A", func=lambda ctx: "a")
        meta_b = CommandMeta(id="test.cmd", display="B", func=lambda ctx: "b")
        clean_registry.register(create_command_from_meta(meta_a))
        clean_registry.register(create_command_from_meta(meta_b))
        cmd_cls = clean_registry.get_command("test.cmd")
        assert cmd_cls.meta.display == "B"

    def test_register_same_id_first_registration_overwritten(self, clean_registry):
        meta_a = CommandMeta(id="test.cmd", display="First", func=lambda ctx: "first")
        meta_b = CommandMeta(id="test.cmd", display="Second", func=lambda ctx: "second")
        clean_registry.register(create_command_from_meta(meta_a))
        clean_registry.register(create_command_from_meta(meta_b))
        cmd_cls = clean_registry.get_command("test.cmd")
        assert cmd_cls.meta.display == "Second"
