import py_compile

from unittest.mock import patch


def test_compile():
    py_compile.compile('afterimages/app/viewer/commands/debug_commands.py')


class TestDebugCommands:
    @patch('afterimages.constants.DEV_MODE', True)
    def test_register_in_dev_mode(self):
        from afterimages.app.viewer.commands.debug_commands import DebugCommands
        DebugCommands.register()

    @patch('afterimages.constants.DEV_MODE', False)
    def test_skip_register_in_normal_mode(self):
        from importlib import reload
        import afterimages.app.viewer.commands.debug_commands as mod
        reload(mod)
