from __future__ import annotations

from typing import Any

from PySide6 import QtWidgets

from ..actions.bridge import Kit
from ..common.logs import AppLogger
from ..os.process import Proc
from ..zmq.message import Msg

def _tray_send(ctx, topic: str, payload=None):
    tray = ctx.get_instance("Tray")
    try:
        tray.broker.inject(Msg.build(topic, payload))
    except Exception as e:
        AppLogger.warning(f'[{topic} notify failed] {e}')

def get_viewer_count(ctx=None) -> int:
    tray = ctx.get_instance("Tray")
    try:
        return tray.broker.get_counts().get('viewer', 0)
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
        Proc.new_main('--viewer')
        return
    tray.show_state = not bool(getattr(tray, 'show_state', False))
    send_show_toggle(ctx, tray.show_state)


def open_new_window(ctx=None):
    AppLogger.info('launching new viewer')
    Proc.new_main('--viewer')


def rescan_all(ctx=None):
    _tray_send(ctx, 'rescan')


def cleanup_optimize(ctx=None):
    _tray_send(ctx, 'cleanup')


def test(ctx=None):
    AppLogger.info('SENDING TEST')
    _tray_send(ctx, 'test', 'TEST FUNCTION!')


def test2(ctx=None):
    AppLogger.info(Proc.get_subset('--collector'))


def quit(ctx=None):
    QtWidgets.QApplication.quit()

class TrayMenu(Kit.MenuBase):
    prefix = "Tray"

    commands = [
        Kit.Command(path="show_window", display="Show Window", func=show_window),
        Kit.Command(path="open_new_window", display="Open New Window", func=open_new_window),
        "-",
        Kit.Command(path="rescan_all", display="ReScan All", func=rescan_all),
        Kit.Command(path="cleanup_optimize", display="Cleanup and Optimize", func=cleanup_optimize),
        "-",
        Kit.Command(path="test", display="Test", func=test),
        Kit.Command(path="test2", display="Test2", func=test2),
        "-",
        Kit.Command(path="quit", display="Quit", func=quit),
    ]


