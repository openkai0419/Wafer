import pytest
from unittest.mock import MagicMock, patch
from PySide6 import QtWidgets

from wafer.core.actions.command.core import (
    CommandRegistry, CommandMeta, create_command_from_meta, CommandBase,
)
from wafer.core.actions.command.context import CommandContext
from wafer.core.actions.command.payload import CommandPayload


@pytest.fixture()
def clean_registry():
    registry = CommandRegistry.instance()
    prev = dict(registry._commands)
    registry._commands = {}
    yield registry
    registry._commands = prev


class TestMenuBuilderSkipsMissing:
    def test_build_into_skips_unknown_command(self, qtbot, clean_registry):
        from wafer.utils.logs import AppLogger
        from wafer.core.actions.command.menu_builder import CommandMenuBuilder

        meta = CommandMeta(id="known_cmd", display="Known", func=lambda ctx: None)
        clean_registry.register(create_command_from_meta(meta))

        builder = CommandMenuBuilder.instance()
        w = QtWidgets.QWidget()
        qtbot.addWidget(w)
        menu = QtWidgets.QMenu(w)

        with patch.object(AppLogger, 'warning') as mock_warn:
            builder.build_into(menu, w, ["known_cmd", "missing_cmd"])
            assert any("missing_cmd" in str(c) for c in mock_warn.call_args_list)

        assert menu.actions()


class TestMenuSpecExecNone:
    def test_exec_returns_none_when_build_fails(self):
        from wafer.core.actions.bridge import MenuSpec, MenuSession
        session = MagicMock(spec=MenuSession)
        session.pos = None
        spec = MenuSpec(session, MagicMock())
        session.build.return_value = None
        result = spec.exec()
        assert result is None


class TestBridgeGetCheckedMissing:
    def test_get_checked_returns_false_for_missing(self, clean_registry):
        from wafer.core.actions.bridge import Command
        result = Command.get_checked("totally_missing_command")
        assert result is False
