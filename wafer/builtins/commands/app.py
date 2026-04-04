from PySide6 import QtWidgets, QtCore
from ...core.commands.bridge import ActionKit
from ...core.platform.process import AppProcess
from ...core.session import SessionStore
from ...core.qt.window import DialogLayoutStore
from ...utils.formatting import dpix


_standalone_dialogs: dict[str, QtWidgets.QDialog] = {}


def _open_standalone(widget_factory, title: str, store_key: str, size=None):
    existing = _standalone_dialogs.get(store_key)
    if existing is not None and existing.isVisible():
        existing.raise_()
        existing.activateWindow()
        return
    dlg = QtWidgets.QDialog()
    dlg.setWindowTitle(title)
    dlg.setWindowFlags(dlg.windowFlags() | QtCore.Qt.Window)
    dlg.setAttribute(QtCore.Qt.WA_DeleteOnClose)
    if size:
        dlg.resize(*size)
    else:
        dlg.resize(dpix(550), dpix(700))
    layout = QtWidgets.QVBoxLayout(dlg)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(widget_factory())
    store = DialogLayoutStore(store_key)
    store.restore(dlg)
    _standalone_dialogs[store_key] = dlg

    def _on_close(event):
        store.save(dlg)
        _standalone_dialogs.pop(store_key, None)
        QtWidgets.QDialog.closeEvent(dlg, event)
    dlg.closeEvent = _on_close
    dlg.show()


def _toggle_or_standalone(ctx, panel_display_name: str, widget_factory, store_key: str, size=None):
    w = ctx.get_instance("MainWindow")
    if w:
        w._layout_manager.toggle_panel(panel_display_name)
        return
    _open_standalone(widget_factory, panel_display_name, store_key, size)


def open_plugin_manager(ctx):
    from ..plugin_manager.widget import PluginManagerWidget
    _toggle_or_standalone(
        ctx, "Plugin Manager",
        PluginManagerWidget, "plugin_manager",
        size=(dpix(550), dpix(1000)),
    )


def open_database_manager(ctx):
    from ..database_manager.widget import DatabaseManagerWidget
    _toggle_or_standalone(
        ctx, "Database Manager",
        DatabaseManagerWidget, "database_manager",
        size=(dpix(500), dpix(700)),
    )


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
    SCOPE = "*"

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


class DatabaseManagerCommands(ActionKit.MenuBase):
    NAME = "Setting"
    PRIORITY = 85
    SCOPE = "*"

    @classmethod
    def commands(cls):
        return [
            ":Database",
            ActionKit.Command(
                path="setting.database_manager",
                display="Database Manager",
                func=open_database_manager,
            ),
        ]
