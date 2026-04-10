from ...core.commands.bridge import ActionKit
from ...core.commands.binding.instance_registry import InstanceRegistry
from ...ui.layout.manager import LayoutManager, MODE_EDIT


def _is_layout_edit():
    w = InstanceRegistry.instance().get_one("MainWindow")
    return w._layout_manager._mode == MODE_EDIT if w else False


def toggle_layout_mode(ctx):
    w = ctx.get_instance("MainWindow")
    if not w:
        return
    w._layout_manager.toggle_mode()


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
                checked_resolver=_is_layout_edit,
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
