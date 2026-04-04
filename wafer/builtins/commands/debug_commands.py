from ...core.commands.bridge import ActionKit
from ...constants import DEV_MODE


class DebugCommands(ActionKit.MenuBase):
    NAME = "Debug"
    PRIORITY = 80

    @classmethod
    def commands(cls):
        return [
            ":Debug",
            ActionKit.Command(path="debug/printCtx", display="Print Ctx", func=lambda ctx: (ctx.print_debug())),
        ]

    @classmethod
    def register(cls):
        if not DEV_MODE:
            return
        super().register()
