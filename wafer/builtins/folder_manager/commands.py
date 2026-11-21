from wafer.builtins.commands.panel import open_panel as show_panel
from wafer.core.lang.manager import t
from wafer.plugin import CommandMeta, MenuGroup, MenuPath
from wafer.qt.commands.binding.instance_registry import InstanceRegistry

from .shared_settings import load_auto_select
from .widget import INSTANCE_NAME, FolderManagerPlugin


def open_panel(ctx):
    widget = ctx.get_instance(INSTANCE_NAME)
    if widget is not None and widget.isVisible():
        return widget
    return show_panel(name=FolderManagerPlugin.DISPLAY_NAME, toggle=False)


def select_matches(ctx):
    widget = open_panel(ctx)
    if widget is not None:
        widget.select_matches()


def toggle_matches_only(ctx):
    widget = open_panel(ctx)
    if widget is not None:
        widget.set_matches_only(not widget.matches_only)


def matches_only_checked() -> bool:
    return getattr(InstanceRegistry.instance().get_one(INSTANCE_NAME), "matches_only", False)


def toggle_auto_select(ctx):
    widget = open_panel(ctx)
    if widget is not None:
        widget.set_auto_select_tree(not widget.auto_select_tree)


def auto_select_checked() -> bool:
    widget = InstanceRegistry.instance().get_one(INSTANCE_NAME)
    return widget.auto_select_tree if widget is not None else load_auto_select()


def collapse_all(ctx):
    widget = open_panel(ctx)
    if widget is not None:
        widget.collapse_all()


class FolderManagerCommands(MenuGroup):
    NAME = f"{MenuPath.WIDGETS}/Folder Manager"
    DEFAULT_ENABLED = True
    PRIORITY = 120
    SCOPE = "*"

    @classmethod
    def commands(cls):
        return [
            ":Folder Manager",
            CommandMeta(path="folder_manager.select_matches", display=t("Select matches"), func=select_matches),
            CommandMeta(path="folder_manager.matches_only", display=t("Matches only"), func=toggle_matches_only, checked=matches_only_checked),
            CommandMeta(path="folder_manager.collapse_all", display=t("Collapse all"), func=collapse_all),
        ]


class FolderManagerViewerCommands(MenuGroup):
    NAME = FolderManagerCommands.NAME
    DEFAULT_ENABLED = True
    PRIORITY = 121
    SCOPE = "viewer"

    @classmethod
    def commands(cls):
        return [
            CommandMeta(path="folder_manager.auto_select_foldertree", display=t("Auto Select FolderTree"), func=toggle_auto_select, checked=auto_select_checked),
        ]
