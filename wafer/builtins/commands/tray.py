from __future__ import annotations

from PySide6 import QtWidgets

from ...core.commands.bridge import ActionKit
from ...utils.logs import AppLogger
from ...constants import DEV_MODE
from ...core.platform.process import AppProcess
from ...core.ipc.message import Message
from ...core.workspace import WorkspaceStore


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
        store = WorkspaceStore.instance()
        restore_ids = store.get_restore_slot_ids()
        if restore_ids:
            AppLogger.info(f"restoring {len(restore_ids)} viewer(s): {restore_ids}")
            for sid in restore_ids:
                AppProcess.new_main("--viewer", "--slot", sid)
        else:
            AppProcess.new_main("--viewer")
        return
    tray.show_state = not bool(getattr(tray, "show_state", False))
    send_show_toggle(ctx, tray.show_state)


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


class TrayViewerCommands(ActionKit.MenuBase):
    NAME = "Viewer"
    SCOPE = "tray"
    PRIORITY = 70

    @classmethod
    def commands(cls):
        return [
            ActionKit.Command(path="tray.show_window", display="Show/Hide Viewer", func=show_window),
        ]


class TrayDatabaseCommands(ActionKit.MenuBase):
    NAME = "Database"
    SCOPE = "tray"
    PRIORITY = 72

    @classmethod
    def commands(cls):
        return [
            ":Database",
            ActionKit.Command(path="tray.rescan_all", display="ReScan All", func=rescan_all),
            ActionKit.Command(path="tray.cleanup_optimize", display="Cleanup and Optimize", func=cleanup_optimize),
        ]


class TraySystemCommands(ActionKit.MenuBase):
    NAME = "Tray"
    SCOPE = "tray"
    PRIORITY = 100

    @classmethod
    def commands(cls):
        items = []
        if DEV_MODE:
            items += [
                ActionKit.Command(path="tray.debug_test", display="Debug Test", func=_debug_test),
                ActionKit.Command(path="tray.debug_test2", display="Debug Test2", func=_debug_test2),
                "-",
            ]
        items += [
            ActionKit.Command(path="tray.quit", display="Quit", func=quit_app),
        ]
        return items
