from PySide6 import QtCore

from ...core.commands.bridge import Command, ActionKit
from ...core.setting.folder_settings import FolderSettings
from ...core.setting.setting_window import SettingsWindow
from ...core.platform.process import AppProcess
from ...core.setting.app_settings import app_settings
from .session_commands import (
    show_session_popup, create_session,
    open_session, rename_session, delete_session, color_session,
    _ss_store,
)


def _win(ctx):
    return ctx.get_instance("MainWindow")


def show_settings(ctx):
    w = _win(ctx)
    if not w:
        return
    window = SettingsWindow(w)
    window.add_tab(FolderSettings())
    window.show()


def toggle_fullscreen(ctx):
    w = _win(ctx)
    if not w:
        return
    w.window_state.toggle_fullscreen()


def toggle_language(ctx):
    w = _win(ctx)
    if not w:
        return
    new_locale = 'ja' if w.t.current_locale == 'en' else 'en'
    w.t.set_locale(new_locale)
    app_settings.save_immediate('window/language', new_locale)


def toggle_always_on_top(ctx):
    w = _win(ctx)
    if not w:
        return
    w.window_state.set_always_on_top(not w.window_state.is_always_on_top)
    Command.set_checked("win.toggle_always_on_top", w.window_state.is_always_on_top)


def _session_names():
    return _ss_store().list_session_names()


def toggle_layout_mode(ctx):
    w = _win(ctx)
    if not w:
        return
    mgr = w._layout_manager
    mgr.toggle_mode()
    from ...core.layout.manager import MODE_EDIT
    Command.set_checked("win.toggle_layout_mode", mgr.mode == MODE_EDIT)


class WindowCommands(ActionKit.MenuBase):
    NAME = "Window"
    PRIORITY = 75

    @classmethod
    def commands(cls):
        return [
            ":Window",
            ActionKit.Command(path="win.show_settings", display="Settings", func=show_settings),
            ActionKit.Command(path="win.toggle_fullscreen", display="Full Screen", func=toggle_fullscreen),
            ActionKit.Command(path="win.toggle_always_on_top", display="Always on Top", func=toggle_always_on_top, checkable=True),
            ActionKit.Command(path="win.toggle_language", display="Toggle Language", func=toggle_language),
            "-",
            ":Panels",
            ActionKit.Command(path="win.toggle_layout_mode", display="Edit Layout", func=toggle_layout_mode, checkable=True),
            "panel.toggle_folder_tree",
            "panel.toggle_search",
            "panel.toggle_grid_view",
            "panel.toggle_file_viewer",
            "panel.toggle_devlog",
            "-",
            ":Session",
            ActionKit.Command(path="win.new_window", display="New Window", func=create_session),
            ActionKit.Command(path="win.session_list", display="Session List", func=show_session_popup),
            ActionKit.Command(
                path="win.open_session", display="Open Session", func=open_session,
                params=[ActionKit.Param(name="session", value=_session_names, required=True)],
            ),
            ActionKit.Command(
                path="win.rename_session", display="Rename Session", func=rename_session,
                params=[ActionKit.Param(name="session", value=_session_names, required=True)],
            ),
            ActionKit.Command(
                path="win.delete_session", display="Delete Session", func=delete_session,
                params=[ActionKit.Param(name="session", value=_session_names, required=True)],
            ),
            ActionKit.Command(
                path="win.session_color", display="Session Color", func=color_session,
                params=[ActionKit.Param(name="session", value=_session_names, required=True)],
            ),
        ]
