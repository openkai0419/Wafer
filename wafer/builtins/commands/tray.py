from __future__ import annotations

from PySide6 import QtWidgets

from ...core.commands.bridge import ActionKit
from ...utils.logs import AppLogger
from ...constants import DEV_MODE
from ...core.platform.process import AppProcess
from ...core.ipc.message import Message
from ...core.qt.dialog import InputDialog
from ...utils.notifier import Notifier
from ...core.session import SessionStore


def _tray_send(ctx, topic: str, payload=None):
    tray = ctx.get_instance("Tray")
    try:
        tray.broker.dispatch(Message.build(topic, payload))
    except Exception as e:
        AppLogger.warning(f"[{topic} notify failed] {e}")


def get_viewer_count(ctx=None) -> int:
    tray = ctx.get_instance("Tray")
    try:
        return tray.broker.peer_counts().get("viewer", 0)
    except Exception as e:
        AppLogger.warning(f"[viewer count failed] {e}")
        return 0


def send_show_toggle(ctx=None, flag: bool = False):
    _tray_send(ctx, "show_toggle", flag)


def show_window(ctx=None):
    tray = ctx.get_instance("Tray")
    c = get_viewer_count(ctx)
    if c < 1:
        store = SessionStore.instance()
        restore_ids = store.get_restore_session_ids()
        if restore_ids:
            AppLogger.info(f"restoring {len(restore_ids)} viewer(s): {restore_ids}")
            for sid in restore_ids:
                AppProcess.new_main("--viewer", "--session", sid)
        else:
            inactive = store.find_inactive_session_id()
            if inactive:
                AppProcess.new_main("--viewer", "--session", inactive)
            else:
                sid = store.create_session_with_unique_name(store.next_default_name())
                AppProcess.new_main("--viewer", "--session", sid)
        return
    tray.show_state = not bool(getattr(tray, "show_state", False))
    send_show_toggle(ctx, tray.show_state)


def open_new_window(ctx=None):
    store = SessionStore.instance()
    default_name = store.next_default_name()
    name = InputDialog.get_text(
        "Session name:",
        title="New Window",
        buttons=("Create", "Cancel"),
        default=default_name,
    )
    if not name or not name.strip():
        return
    name = name.strip()
    sid = store.create_session(name)
    if sid is None:
        existing = store.find_session_by_name(name)
        if existing:
            if existing.session_id in store.get_active_session_ids():
                Notifier.warning(f"Session already open: {name}")
            else:
                AppProcess.new_main("--viewer", "--session", existing.session_id)
        return
    AppLogger.info(f"launching new viewer: {sid}")
    AppProcess.new_main("--viewer", "--session", sid)


def rescan_all(ctx=None):
    _tray_send(ctx, "rescan")


def cleanup_optimize(ctx=None):
    _tray_send(ctx, "cleanup")


def _debug_test(ctx=None):
    AppLogger.info("SENDING TEST")
    _tray_send(ctx, "test", "TEST FUNCTION!")


def _debug_test2(ctx=None):
    AppLogger.info(AppProcess.get_by_args_subset("--indexer"))


def quit_app(ctx=None):
    QtWidgets.QApplication.quit()


class TrayMenu(ActionKit.MenuBase):
    NAME = "Tray"
    SCOPE = "tray"

    @classmethod
    def commands(cls):
        items = [
            ":Wafer",
            ActionKit.Command(path="show_window", display="Show Viewer", func=show_window),
            ActionKit.Command(path="open_new_window", display="New Viewer", func=open_new_window),
            "-",
            ":Database",
            ActionKit.Command(path="rescan_all", display="ReScan All", func=rescan_all),
            ActionKit.Command(path="cleanup_optimize", display="Cleanup and Optimize", func=cleanup_optimize),
            "-",
            ":Popups",
            "setting.database_manager",
            "setting.plugin_manager",
            "setting.batch_renamer",
        ]
        if DEV_MODE:
            items += [
                "-",
                ActionKit.Command(path="debug_test", display="Debug Test", func=_debug_test),
                ActionKit.Command(path="debug_test2", display="Debug Test2", func=_debug_test2),
            ]
        items += [
            "-",
            ActionKit.Command(path="quit", display="Quit", func=quit_app),
        ]
        return items
