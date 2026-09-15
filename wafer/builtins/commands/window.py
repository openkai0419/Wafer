import webbrowser

from ...qt.commands.bridge import ActionKit
from ...qt.commands.binding.instance_registry import InstanceRegistry
from ...core.platform.process import AppProcess
from ...core.workspace import WorkspaceStore
from ...plugin import installer_queue
from ...plugin.loader import get_plugin_dir
from ...utils.logs import AppLogger
from ...utils.notifier import Notifier
from .workspace import new_window


def _win(ctx):
    return ctx.get_instance("MainWindow")


def _host(ctx):
    return _win(ctx) or ctx.get_instance("WebUIWindow")


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
    from ...plugin.settings import PluginSettings

    PluginSettings().clear_restart_scope()

    if installer_queue.has_pending_queue(get_plugin_dir()):
        store = WorkspaceStore.instance()
        store.set_restore_slot_ids(store.get_active_slot_ids())
        Notifier.info("Restarting to install extensions")
        _shutdown_all(ctx, then_restart=True)
        return

    w = _win(ctx)
    if w:
        w._perform_system_restart(include_self=True)
        w.close_by_restart()
        return
    if ctx.get_instance("WebUIWindow"):
        _shutdown_all(ctx, then_restart=True)
        return
    store = WorkspaceStore.instance()
    store.set_restore_slot_ids(store.get_active_slot_ids())
    AppProcess.terminate_cmd("--tray", wait=True)
    AppProcess.new_main("--tray")


def close_all(ctx):
    _shutdown_all(ctx, then_restart=False)


def _shutdown_via_tray(ctx, *, then_restart):
    tray = ctx.get_instance("Tray")
    if tray:
        (tray.restart_all if then_restart else tray.close_all)()
        return True
    host = _host(ctx)
    node = getattr(host, "_node", None) if host else None
    if node and AppProcess.get_by_args_subset("--tray"):
        node.send("app.restart_all" if then_restart else "app.quit_all", dst="tray")
        return True
    return False


def _shutdown_all(ctx, *, then_restart):
    if _shutdown_via_tray(ctx, then_restart=then_restart):
        return

    w = _host(ctx)
    if not w:
        return

    AppLogger.info(f"shutdown_all(restart={then_restart}): tray unreachable, force-terminating all app processes")
    webui_running = bool(AppProcess.get_by_args_subset("--webui"))
    AppProcess.force_close_all()
    if then_restart:
        if webui_running:
            WorkspaceStore.instance().set_restore_webui(True)
        AppProcess.new_main()
    if hasattr(w, "_close_reason"):
        from ...app.lifecycle import CloseReason

        w._close_reason = CloseReason.SHUTDOWN
    w.close()


def open_webui(ctx=None):
    from ...app.webui.state import read_url

    if AppProcess.get_by_args_subset("--webui"):
        url = read_url()
        if url:
            AppLogger.info(f"WebUI already running, opening {url}")
            webbrowser.open(url)
        return
    AppProcess.new_main("--webui")


class WindowPanelCommands(ActionKit.MenuBase):
    NAME = "Window"
    PRIORITY = 83

    @classmethod
    def commands(cls):
        return [
            ":Window",
            ActionKit.Command(path="win.toggle_fullscreen", display="Full Screen", func=toggle_fullscreen),
            ActionKit.Command(path="win.toggle_always_on_top", display="Always on Top", func=toggle_always_on_top, checked=_is_always_on_top),
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
            ActionKit.Command(path="webui.open", display="Open WebUI", func=open_webui),
            "-",
            ":Restart",
            ActionKit.Command(path="win.restart_all", display="Restart All", func=restart_all),
            ActionKit.Command(path="win.restart_tray", display="Restart Tray", func=restart_tray),
            ActionKit.Command(path="win.restart_viewer", display="Restart Viewer", func=restart_viewer),
            "-",
            ":Quit",
            ActionKit.Command(path="win.close_all", display="Quit All", func=close_all),
        ]
