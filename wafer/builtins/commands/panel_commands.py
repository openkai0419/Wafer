from ...core.commands.bridge import ActionKit
from ...core.layout.manager import LayoutManager


def toggle_layout_mode(ctx):
    from ...core.commands.bridge import Command
    w = ctx.get_instance("MainWindow")
    if not w:
        return
    mgr = w._layout_manager
    mgr.toggle_mode()
    from ...core.layout.manager import MODE_EDIT
    Command.set_checked("win.toggle_layout_mode", mgr.mode == MODE_EDIT)


class PanelCommands(ActionKit.MenuBase):
    NAME = "Panel"
    PRIORITY = 76

    _CORE_PANELS = ["Toolbar", "Folder Tree", "Search", "Grid View", "File Viewer"]

    @classmethod
    def commands(cls):
        from ...plugin.panel.handler import panel_registry
        items: list = [
            ":Panel",
            ActionKit.Command(
                path="win.toggle_layout_mode",
                display="Edit Layout",
                func=toggle_layout_mode,
                checkable=True,
            ),
            "-",
        ]
        for name in cls._CORE_PANELS:
            items.append(LayoutManager._command_id(name))
        for plugin_cls in panel_registry.list_all():
            name = plugin_cls.DISPLAY_NAME or plugin_cls.NAME
            items.append(LayoutManager._command_id(name))
        return items
