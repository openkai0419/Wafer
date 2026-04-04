from ...core.commands.bridge import ActionKit
from ...constants import DEV_MODE

def toggle_dev_log(ctx):
    from wafer.app.viewer.widgets.dev_log_panel import DevLogPanel
    panel = DevLogPanel.instance()
    if panel is None:
        return
    panel.setVisible(not panel.isVisible())


class DebugCommands(ActionKit.MenuBase):
    NAME = "Debug"
    PRIORITY = 80

    @classmethod
    def commands(cls):
        return [
            ":Debug",
            ActionKit.Command(path="dev.toggle_log_panel", display="Toggle Log Panel", func=toggle_dev_log),
            ActionKit.Command(path="debug/printCtx", display="Print Ctx", func=lambda ctx: (ctx.print_debug())),
        ]

    @classmethod
    def register(cls):
        if not DEV_MODE:
            return
        super().register()
