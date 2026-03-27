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


@require(fv="FileViewerWidget")
def toggle_slideshow(ctx, fv, interval_ms: int = 3000, loop: bool = True):
    fv.toggle_autoplay(
        interval_ms=int(interval_ms),
        loop=bool(loop),
    )


@require(fv="FileViewerWidget")
def start_slideshow(ctx, fv, interval_ms: int = 3000, loop: bool = True):
    fv.start_autoplay(
        interval_ms=int(interval_ms),
        loop=bool(loop),
    )


@require(fv="FileViewerWidget")
def stop_slideshow(ctx, fv):
    fv.stop_autoplay()


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
            ActionKit.Command(
                path="fv.toggle_slideshow",
                display="Slideshow",
                func=toggle_slideshow,
                checkable=True,
                params=[
                    ActionKit.Param(name="interval_ms", value=3000, min_value=500, max_value=60000),
                    ActionKit.Param(name="loop", value=True),
                ],
            ),
            ActionKit.Command(
                path="fv.start_slideshow",
                display="Start Slideshow",
                func=start_slideshow,
                hidden=True,
                params=[
                    ActionKit.Param(name="interval_ms", value=3000, min_value=500, max_value=60000),
                    ActionKit.Param(name="loop", value=True),
                ],
            ),
            ActionKit.Command(
                path="fv.stop_slideshow",
                display="Stop Slideshow",
                func=stop_slideshow,
                hidden=True,
            ),
            "-",
        ]
