from ...core.commands.bridge import ActionKit
from ...core.commands.binding.instance_registry import InstanceRegistry
from ...core.app_settings import app_settings
from ...core.lang.manager import t
from ...utils.notifier import Notifier
from .profile_commands import (
    show_profile_popup,
    create_profile,
    new_window,
    open_profile,
    open_profile_in_new_window,
    rename_profile,
    delete_profile,
    _pf_store,
)


def _win(ctx):
    return ctx.get_instance("MainWindow")


def toggle_fullscreen(ctx):
    w = _win(ctx)
    if not w:
        return
    w.window_state.toggle_fullscreen()


def toggle_language(ctx):
    w = _win(ctx)
    if not w:
        return
    new_locale = "ja" if t.current_locale == "en" else "en"
    app_settings.save_immediate("window/language", new_locale)
    Notifier.info(f"Language set to '{new_locale}'. Restart to apply.")


def toggle_always_on_top(ctx):
    w = _win(ctx)
    if not w:
        return
    w.window_state.set_always_on_top(not w.window_state.is_always_on_top)


def _is_always_on_top():
    w = InstanceRegistry.instance().get_one("MainWindow")
    return w.window_state.is_always_on_top if w else False


def _profile_names():
    return _pf_store().list_profile_names()


class WindowCommands(ActionKit.MenuBase):
    NAME = "Window"
    PRIORITY = 75

    @classmethod
    def commands(cls):
        return [
            ":Window",
            ActionKit.Command(path="win.toggle_fullscreen", display="Full Screen", func=toggle_fullscreen),
            ActionKit.Command(path="win.toggle_always_on_top", display="Always on Top", func=toggle_always_on_top, checkable=True, checked_resolver=_is_always_on_top),
            ActionKit.Command(path="win.toggle_language", display="Toggle Language", func=toggle_language),
            "-",
            ":Profile",
            ActionKit.Command(path="win.new_profile", display="New Profile", func=create_profile),
            ActionKit.Command(path="win.new_window", display="New Window", func=new_window),
            ActionKit.Command(path="win.profile_list", display="Profile List", func=show_profile_popup),
            ActionKit.Command(
                path="win.open_profile",
                display="Open Profile",
                func=open_profile,
                params=[ActionKit.Param(name="profile", value=_profile_names, required=True)],
            ),
            ActionKit.Command(
                path="win.open_profile_in_new_window",
                display="Open Profile in New Window",
                func=open_profile_in_new_window,
                params=[ActionKit.Param(name="profile", value=_profile_names, required=True)],
            ),
            ActionKit.Command(
                path="win.rename_profile",
                display="Rename Profile",
                func=rename_profile,
                params=[ActionKit.Param(name="profile", value=_profile_names, required=True)],
            ),
            ActionKit.Command(
                path="win.delete_profile",
                display="Delete Profile",
                func=delete_profile,
                params=[ActionKit.Param(name="profile", value=_profile_names, required=True)],
            ),
        ]
