from ...core.commands.bridge import ActionKit
from ...ui.layout.manager import LayoutManager


def toggle_layout_mode(ctx):
    from ...core.commands.bridge import Command

    w = ctx.get_instance("MainWindow")
    if not w:
        return
    mgr = w._layout_manager
    mgr.toggle_mode()
    from ...ui.layout.manager import MODE_EDIT

    Command.set_checked("win.toggle_layout_mode", mgr.mode == MODE_EDIT)


class PanelCommands(ActionKit.MenuBase):
    NAME = "Panels"
    PRIORITY = 76

    _CORE_PANELS = ["Toolbar", "Folder Tree", "Search", "Grid View", "Content Viewer", "Meta Viewer"]

    @classmethod
    def commands(cls):
        from ...plugin.panel.handler import panel_registry

        items: list = [
            ":Edit",
            ActionKit.Command(
                path="win.toggle_layout_mode",
                display="Edit Mode (might have visual issues)",
                func=toggle_layout_mode,
                checkable=True,
            ),
            "-",
        ]
        for name in cls._CORE_PANELS:
            items.append(LayoutManager._command_id(name))

        builtins = []
        plugins = []
        for plugin_cls in panel_registry.list_all():
            name = plugin_cls.DISPLAY_NAME or plugin_cls.NAME
            cmd_id = LayoutManager._command_id(name)
            if getattr(plugin_cls, "SOURCE", "Plugin") == "Builtin":
                builtins.append(cmd_id)
            else:
                plugins.append(cmd_id)

        if builtins:
            items.append("-")
            items.extend(builtins)
        if plugins:
            items.append("-")
            items.extend(plugins)
        return items
