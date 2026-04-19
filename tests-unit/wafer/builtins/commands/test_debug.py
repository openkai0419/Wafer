import py_compile

from unittest.mock import patch


def test_compile():
    py_compile.compile("wafer/builtins/commands/debug.py")


class TestDebugCommands:
    @patch("wafer.constants.DEV_MODE", True)
    def test_register_in_dev_mode(self):
        from wafer.builtins.commands.debug import DebugCommands

        DebugCommands.register()

    @patch("wafer.builtins.commands.debug.DEV_MODE", False)
    def test_skip_register_in_normal_mode(self):
        from wafer.builtins.commands.debug import DebugCommands

        with patch.object(DebugCommands, "commands", wraps=DebugCommands.commands) as mock_cmds:
            DebugCommands.register()
            mock_cmds.assert_not_called()
