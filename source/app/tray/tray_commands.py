from __future__ import annotations

from typing import Any

from PySide6 import QtWidgets

from source.core.actions.bridge import ActionKit
from source.utils.logs import AppLogger
from source.constants import DEV_MODE
from source.core.platform.process import AppProcess
from source.core.zmq.message import Message
def _tray_send(ctx, topic: str, payload=None):
    tray = ctx.get_instance("Tray")
    try:
        tray.broker.dispatch(Message.build(topic, payload))
    except Exception as e:
        AppLogger.warning(f'[{topic} notify failed] {e}')

def get_viewer_count(ctx=None) -> int:
    tray = ctx.get_instance("Tray")
    try:
        return tray.broker.peer_counts().get('viewer', 0)
    except Exception as e:
        AppLogger.warning(f'[viewer count failed] {e}')
        return 0

def send_show_toggle(ctx=None, flag: bool = False):
    _tray_send(ctx, 'show_toggle', flag)


def show_window(ctx=None):
    tray = ctx.get_instance("Tray")
    c = get_viewer_count(ctx)
    if c < 1:
        AppLogger.info('launching new viewer')
        AppProcess.new_main('--viewer')
        return
    tray.show_state = not bool(getattr(tray, 'show_state', False))
    send_show_toggle(ctx, tray.show_state)


def open_new_window(ctx=None):
    AppLogger.info('launching new viewer')
    AppProcess.new_main('--viewer')


def rescan_all(ctx=None):
    _tray_send(ctx, 'rescan')


def cleanup_optimize(ctx=None):
    _tray_send(ctx, 'cleanup')


def _debug_test(ctx=None):
    AppLogger.info('SENDING TEST')
    _tray_send(ctx, 'test', 'TEST FUNCTION!')


def _debug_test2(ctx=None):
    AppLogger.info(AppProcess.get_by_args_subset('--indexer'))


def quit_app(ctx=None):
    QtWidgets.QApplication.quit()

class TrayMenu(ActionKit.MenuBase):
    NAME = "Tray"

    @classmethod
    def commands(cls):
        items = [
            ActionKit.Command(path="show_window", display="Show Window", func=show_window),
            ActionKit.Command(path="open_new_window", display="Open New Window", func=open_new_window),
            "-",
            ActionKit.Command(path="rescan_all", display="ReScan All", func=rescan_all),
            ActionKit.Command(path="cleanup_optimize", display="Cleanup and Optimize", func=cleanup_optimize),
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


