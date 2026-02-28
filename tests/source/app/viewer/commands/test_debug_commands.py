import py_compile

from unittest.mock import patch


def test_compile():
    py_compile.compile('source/app/viewer/commands/debug_commands.py')


class TestDebugCommands:
    @patch('source.constants.DEV_MODE', True)
    def test_register_in_dev_mode(self):
        from source.app.viewer.commands.debug_commands import DebugCommands
        DebugCommands.register()

    @patch('source.constants.DEV_MODE', False)
    def test_skip_register_in_normal_mode(self):
        from importlib import reload
        import source.app.viewer.commands.debug_commands as mod
        reload(mod)
