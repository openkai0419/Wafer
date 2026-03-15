from ....core.commands.bridge import ActionKit
from ....core.commands.command.require import require


def _ensure_current_initialized(model) -> bool:
    if model.count() <= 0:
        return False
    cur = model.current_index()
    if cur is None:
        model.set_current_index(0)
        return model.current_index() is not None
    return True


@require(model="FileViewModel")
def next_file(ctx, model, step: int = 1, loop: bool = False):
    if not _ensure_current_initialized(model):
        return
    model.move_current_next(step=int(step), loop=bool(loop))


@require(model="FileViewModel")
def prev_file(ctx, model, step: int = 1, loop: bool = False):
    if not _ensure_current_initialized(model):
        return
    model.move_current_prev(step=int(step), loop=bool(loop))


class FileViewerCommands(ActionKit.MenuBase):
    NAME = "FileViewer"
    PRIORITY = 50

    @classmethod
    def commands(cls):
        return [
            ":FileViewer",
            ActionKit.Command(
                path="fv.prev_file",
                display="Prev File",
                func=prev_file,
                params=[ActionKit.Param(name="step", value=1), ActionKit.Param(name="loop", value=False)],
            ),
            ActionKit.Command(
                path="fv.next_file",
                display="Next File",
                func=next_file,
                params=[ActionKit.Param(name="step", value=1), ActionKit.Param(name="loop", value=False)],
            ),
            "-",
        ]
