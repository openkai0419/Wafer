from ...core.commands.bridge import ActionKit
from ...core.platform.process import AppProcess
from ...app.viewer.session import SessionStore


def _resolve_node(ctx):
    w = ctx.get_instance("MainWindow")
    if w:
        return w, getattr(w, '_node', None)
    tray = ctx.get_instance("Tray")
    if tray:
        return None, getattr(tray, '_node', None)
    return None, None


def open_plugin_manager(ctx):
    parent, node = _resolve_node(ctx)
    from .window import PluginManagerDialog
    PluginManagerDialog.open(parent=parent, node=node)


def restart_tray(ctx):
    AppProcess.terminate_cmd('--tray')
    AppProcess.new_main('--tray')


def restart_viewer(ctx):
    w = ctx.get_instance("MainWindow")
    if w:
        w.close_by_restart()


def restart_all(ctx):
    w = ctx.get_instance("MainWindow")
    node = getattr(w, '_node', None)
    store = SessionStore.instance()
    active_ids = store.get_active_session_ids()
    own_sid = getattr(w, 'session_id', None)

    store.set_restore_session_ids(active_ids)

    if node:
        for sid in active_ids:
            if sid != own_sid:
                node.send('session.restart', sid, dst='viewer')

    AppProcess.terminate_cmd('--tray')
    AppProcess.new_main('--tray')

    if w:
        w.close_by_restart()


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
