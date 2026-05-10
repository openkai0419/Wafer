from ...core.commands.bridge import ActionKit
from ...core.commands.binding.instance_registry import InstanceRegistry
from ...core.platform.process import AppProcess
from ...core.workspace import WorkspaceStore
from ...plugin import installer_queue
from ...plugin.loader import get_plugin_dir
from ...utils.logs import AppLogger
from ...utils.notifier import Notifier
from .workspace import new_window


def _win(ctx):
    return ctx.get_instance("MainWindow")


def toggle_fullscreen(ctx):
    w = _win(ctx)
    if not w:
        return
    w.window_state.toggle_fullscreen()


def toggle_always_on_top(ctx):
    w = _win(ctx)
    if not w:
        return
    w.window_state.set_always_on_top(not w.window_state.is_always_on_top)


def _is_always_on_top():
    w = InstanceRegistry.instance().get_one("MainWindow")
    return w.window_state.is_always_on_top if w else False


def restart_tray(ctx):
    if installer_queue.has_pending_queue(get_plugin_dir()):
        AppLogger.info("restart_tray: pending install detected, promoting to restart_all")
        Notifier.info("Pending install detected, restarting all windows")
        restart_all(ctx)
        return
    AppProcess.terminate_cmd("--tray", wait=True)
    AppProcess.new_main("--tray")


def restart_viewer(ctx):
    w = _win(ctx)
    if w:
        w.close_by_restart()


def restart_all(ctx):
    w = _win(ctx)

    from ...plugin.settings import PluginSettings

    PluginSettings().clear_restart_scope()

    if w:
        w._perform_system_restart(include_self=True)
        w.close_by_restart()
    else:
        store = WorkspaceStore.instance()
        store.set_restore_slot_ids(store.get_active_slot_ids())
        AppProcess.terminate_cmd("--tray", wait=True)
        AppProcess.new_main("--tray")


class WindowPanelCommands(ActionKit.MenuBase):
    NAME = "Window"
    PRIORITY = 83

    @classmethod
    def commands(cls):
        return [
            ":Window",
            ActionKit.Command(path="win.toggle_fullscreen", display="Full Screen", func=toggle_fullscreen),
            ActionKit.Command(path="win.toggle_always_on_top", display="Always on Top", func=toggle_always_on_top, checkable=True, checked_resolver=_is_always_on_top),
        ]


class WindowRestartCommands(ActionKit.MenuBase):
    NAME = "Window"
    PRIORITY = 82
    SCOPE = "*"

    @classmethod
    def commands(cls):
        return [
            ":Process",
            ActionKit.Command(path="win.new_window", display="New Window", func=new_window),
            "-",
            ":Restart",
            ActionKit.Command(path="win.restart_all", display="Restart All", func=restart_all),
            ActionKit.Command(path="win.restart_tray", display="Restart Tray", func=restart_tray),
            ActionKit.Command(path="win.restart_viewer", display="Restart Viewer", func=restart_viewer),
        ]
