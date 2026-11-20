from __future__ import annotations

from PySide6 import QtWidgets

from ...app.webui.instance import restore_webui
from ...qt.commands.bridge import ActionKit
from ...core.logs import AppLogger
from ...constants import DEV_MODE
from ...core.platform.process import AppProcess
from ...core.ipc.message import Message
from ...core.platform.workspace_lock import WorkspaceLock
from ...core.store.workspace import WorkspaceStore


def _tray_send(ctx, topic: str, payload=None):
    tray = ctx.get_instance("Tray")
    try:
        tray.broker.dispatch(Message.build(topic, payload))
    except Exception as e:
        AppLogger.warning(f"[{topic} notify failed] {e}")


def send_show_toggle(ctx=None, flag: bool = False):
    _tray_send(ctx, "show_toggle", flag)


def show_window(ctx=None):
    store = WorkspaceStore.instance()
    if not WorkspaceLock.open_slot_ids(slot.slot_id for slot in store.list_slots()):
        restore_ids = store.get_restore_slot_ids()
        if restore_ids:
            AppLogger.info(f"restoring {len(restore_ids)} viewer(s): {restore_ids}")
            for sid in restore_ids:
                AppProcess.new_main("--viewer", "--slot", sid)
        else:
            AppProcess.new_main("--viewer")
        restore_webui()
        return
    tray = ctx.get_instance("Tray")
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
    NAME = ActionKit.MenuPath.PROCESS
    SCOPE = "tray"
    PRIORITY = 70

    @classmethod
    def commands(cls):
        return [
            ActionKit.Command(path="tray.show_window", display="Show/Hide Viewer", func=show_window),
        ]


class TrayDatabaseCommands(ActionKit.MenuBase):
    NAME = ActionKit.MenuPath.WORKSPACE
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
    NAME = ActionKit.MenuPath.PROCESS
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
            ActionKit.Command(path="tray.quit", display="Quit Tray", func=quit_app),
        ]
        return items
