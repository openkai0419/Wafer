from ...actions.bridge import Kit
from ...constants import DEV_MODE


def toggle_dev_log(ctx):
    from ..widgets.dev_log_panel import DevLogPanel
    panel = DevLogPanel.instance()
    if panel is None:
        return
    panel.setVisible(not panel.isVisible())


class DebugCommands(Kit.MenuBase):
    prefix = "Debug"

    commands = [
        ":Debug",
        Kit.Command(path="dev.toggle_log_panel", display="Toggle Log Panel", func=toggle_dev_log),
        Kit.Command(path="debug/printCtx", display="Print Ctx", func=lambda ctx: (ctx.print_debug())),
]

    @classmethod
    def register(cls):
        if not DEV_MODE:
            return
        super().register()
