from __future__ import annotations

from ...qt.commands.bridge import ActionKit
from ...core.common.profile import current_profile
from ...core.lang.manager import t
from ...core.logs import AppLogger


def check_for_updates(ctx):
    if current_profile() is not None:
        AppLogger.info(f"Update check skipped: the debug profile {current_profile()} never updates")
        return
    from .startup import present_updater

    widget = present_updater()
    if widget is not None and hasattr(widget, "check_now"):
        widget.check_now()


class UpdateCommands(ActionKit.MenuBase):
    NAME = ActionKit.MenuPath.SETTING
    PRIORITY = 90
    SCOPE = "*"

    @classmethod
    def commands(cls):
        return [
            ":Update",
            ActionKit.Command(path="update.check", display=t("Check for Updates"), func=check_for_updates, hidden=current_profile() is not None),
        ]
