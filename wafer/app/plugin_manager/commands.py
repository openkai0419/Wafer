from ...core.commands.bridge import ActionKit
from ...core.platform.process import AppProcess


def open_plugin_manager(ctx):
    parent = ctx.get_instance("MainWindow")
    node = getattr(parent, '_node', None)
    from .window import PluginManagerDialog
    PluginManagerDialog.open(parent=parent, node=node)


def restart_tray(ctx):
    AppProcess.terminate_cmd('--tray')
    AppProcess.new_main('--tray')


def restart_viewer(ctx):
    from PySide6 import QtWidgets
    w = ctx.get_instance("MainWindow")
    session_id = getattr(w, 'session_id', None)
    args = ['--viewer']
    if session_id:
        args += ['--session', session_id]
    AppProcess.new_main(*args)
    if w:
        w.close()


def restart_all(ctx):
    AppProcess.terminate_cmd('--tray')
    AppProcess.new_main('--tray')
    w = ctx.get_instance("MainWindow")
    session_id = getattr(w, 'session_id', None)
    args = ['--viewer']
    if session_id:
        args += ['--session', session_id]
    AppProcess.new_main(*args)
    if w:
        w.close()


class PluginManagerCommands(ActionKit.MenuBase):
    NAME = "Setting"
    PRIORITY = 85

    @classmethod
    def commands(cls):
        return [
            ":Plugins",
            ActionKit.Command(
                path="setting.plugin_manager",
                display="Plugin Manager",
                func=open_plugin_manager,
            ),
            ActionKit.Command(
                path="setting.restart_all",
                display="Restart All",
                func=restart_all,
            ),
            ActionKit.Command(
                path="setting.restart_tray",
                display="Restart Background Services",
                func=restart_tray,
            ),
            ActionKit.Command(
                path="setting.restart_viewer",
                display="Restart Viewer",
                func=restart_viewer,
            ),
        ]
