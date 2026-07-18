from __future__ import annotations

from ...core.commands.bridge import ActionKit
from ...core.commands.binding.instance_registry import InstanceRegistry
from ...core.lang.manager import t
from .widget import PANEL_DISPLAY_NAME


def check_for_updates(ctx):
    main_window = InstanceRegistry.instance().get_one("MainWindow")
    manager = getattr(main_window, "_layout_manager", None) if main_window else None
    if manager is None or PANEL_DISPLAY_NAME not in manager.panel_names():
        return
    manager.ensure_panel_visible(PANEL_DISPLAY_NAME)
    widget = manager.panel_widget(PANEL_DISPLAY_NAME)
    if hasattr(widget, "check_now"):
        widget.check_now(explicit=True)


class UpdateCommands(ActionKit.MenuBase):
    NAME = "Setting"
    PRIORITY = 90
    SCOPE = "viewer"

    @classmethod
    def commands(cls):
        return [
            ":Update",
            ActionKit.Command(path="update.check", display=t("Check for Updates"), func=check_for_updates),
        ]
