from unittest.mock import patch


class TestDebugCommands:
    @patch("wafer.builtins.commands.debug.DEV_MODE", False)
    def test_skip_register_in_normal_mode(self):
        from wafer.builtins.commands.debug import DebugCommands

        with patch.object(DebugCommands, "commands", wraps=DebugCommands.commands) as mock_cmds:
            DebugCommands.register()
            mock_cmds.assert_not_called()
