from wafer.core.lang.manager import t
from wafer.plugin import CommandMeta, MenuGroup, MenuPath
from wafer.qt.common.notifier import Notifier

from .widget import INSTANCE_NAME


def run_on_panel(ctx, select: bool) -> None:
    widget = ctx.get_instance(INSTANCE_NAME)
    if widget is None:
        Notifier.info(t("Open Folder Manager first"))
        return
    widget.expand_to_matches(select=select)


def expand_matches(ctx):
    run_on_panel(ctx, select=False)


def select_matches(ctx):
    run_on_panel(ctx, select=True)


class FolderManagerCommands(MenuGroup):
    NAME = f"{MenuPath.WIDGETS}/Folder Manager"
    DEFAULT_ENABLED = True
    PRIORITY = 120
    SCOPE = "*"

    @classmethod
    def commands(cls):
        return [
            ":Folder Manager",
            CommandMeta(path="folder_manager.expand_matches", display=t("Expand to matches"), func=expand_matches),
            CommandMeta(path="folder_manager.select_matches", display=t("Select matches"), func=select_matches),
        ]
