from __future__ import annotations

from ...qt.commands.bridge import ActionKit
from ...core.lang.manager import t


def check_for_updates(ctx):
    from .startup import present_updater

    widget = present_updater()
    if widget is not None and hasattr(widget, "check_now"):
        widget.check_now(explicit=True)


class UpdateCommands(ActionKit.MenuBase):
    NAME = "Setting"
    PRIORITY = 90
    SCOPE = "*"

    @classmethod
    def commands(cls):
        return [
            ":Update",
            ActionKit.Command(path="update.check", display=t("Check for Updates"), func=check_for_updates),
        ]
