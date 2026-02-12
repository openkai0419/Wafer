from PySide6 import QtCore

from ...actions.bridge import Command, Kit
from ...os.process import Proc
from ...qt.window import WindowSnapshot, safe_set_window_flag


def _win(ctx):
    return ctx.get_instance("MainWindow")


def show_settings(ctx):
    w = _win(ctx)
    if w:
        w.show_settings()


def toggle_fullscreen(ctx):
    w = _win(ctx)
    if w:
        w.toggle_fullscreen()


def toggle_language(ctx):
    w = _win(ctx)
    if w:
        w.toggle_language()


def toggle_always_on_top(ctx):
    w = _win(ctx)
    if not w:
        return
    on_top = bool(w.windowFlags() & QtCore.Qt.WindowStaysOnTopHint)
    safe_set_window_flag(w, QtCore.Qt.WindowStaysOnTopHint, not on_top)


def open_new_window(ctx):
    Proc.new_main('--viewer')


def restore_always_on_top(window):
    if Command.get_checked("win.toggle_always_on_top"):
        window.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, True)


class WindowCommands(Kit.MenuBase):
    prefix = "Window"

    commands = [
        ":Window",
        Kit.Command(path="win.show_settings", display="Settings", func=show_settings),
        Kit.Command(path="win.toggle_fullscreen", display="Full Screen", func=toggle_fullscreen),
        Kit.Command(path="win.toggle_always_on_top", display="Always on Top", func=toggle_always_on_top, checkable=True),
        Kit.Command(path="win.open_new_window", display="Open New Window", func=open_new_window),
        Kit.Command(path="win.toggle_language", display="Toggle Language", func=toggle_language),
    ]
