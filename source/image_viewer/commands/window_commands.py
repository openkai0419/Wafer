from PySide6 import QtCore

from ...actions.bridge import Command, Kit
from ...image_setting.db_settings import DataBaseSettings
from ...image_setting.setting_window import SettingsWindow
from ...os.process import Proc
from ...qt.window import WindowSnapshot, safe_set_window_flag
from ..viewer_settings import main_setting


def _win(ctx):
    return ctx.get_instance("MainWindow")


def show_settings(ctx):
    w = _win(ctx)
    if not w:
        return
    window = SettingsWindow(w)
    window.add_tab(DataBaseSettings())
    window.show()


def toggle_fullscreen(ctx):
    w = _win(ctx)
    if not w:
        return
    if not (w.windowState() & QtCore.Qt.WindowFullScreen):
        w._pre_fullscreen_snap = WindowSnapshot(w)
        w.showFullScreen()
    else:
        if w._pre_fullscreen_snap:
            w._pre_fullscreen_snap.restore(w)
            w._pre_fullscreen_snap = None
        else:
            w.showNormal()


def toggle_language(ctx):
    w = _win(ctx)
    if not w:
        return
    new_locale = 'ja' if w.t.current_locale == 'en' else 'en'
    w.t.set_locale(new_locale)
    main_setting.save_important('window/language', new_locale)


def toggle_always_on_top(ctx):
    w = _win(ctx)
    if not w:
        return
    on_top = bool(w.windowFlags() & QtCore.Qt.WindowStaysOnTopHint)
    safe_set_window_flag(w, QtCore.Qt.WindowStaysOnTopHint, not on_top)
    Command.set_checked("win.toggle_always_on_top", not on_top)


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
