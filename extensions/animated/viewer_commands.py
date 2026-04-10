from wafer.plugin import MenuGroup, CommandMeta, require
from wafer.core.commands.binding.instance_registry import InstanceRegistry


def _avw():
    return InstanceRegistry.instance().get_one("AnimatedViewerWidget")


@require(vw="AnimatedViewerWidget")
def toggle_fit_mode(ctx, vw):
    vw.toggle_fit_mode()


class AnimatedViewerCommands(MenuGroup):
    NAME = "FileViewer"
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
                checked_resolver=lambda: getattr(_avw(), "cover_mode", False),
            ),
        ]
