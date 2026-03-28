from wafer.plugin import MenuGroup, CommandMeta, require
from wafer.core.commands.bridge import Command


@require(vw="AnimatedViewerWidget")
def toggle_fit_mode(ctx, vw):
    vw.toggle_fit_mode()


class AnimatedViewerCommands(MenuGroup):
    NAME = "Animated Viewer"
    PRIORITY = 1200
    DEFAULT_ENABLED = True

    @classmethod
    def commands(cls):
        return [
            ":Animated Viewer",
            CommandMeta(
                path="aview.toggle_fit_mode",
                display="Contain/Cover",
                func=toggle_fit_mode,
                checkable=True,
            ),
        ]
