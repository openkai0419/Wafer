from ...core.commands.bridge import ActionKit, Command
from ...core.commands.command.require import require
from ...app.viewer.preview.file_list_provider import ListMode


GROUP_LIST_MODE = "fv_list_mode"


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


@require(fv="FileViewerController")
def toggle_slideshow(ctx, fv, interval: float = 3.0, loop: bool = True):
    fv.toggle_autoplay(
        interval_ms=int(float(interval) * 1000),
        loop=bool(loop),
    )


@require(fv="FileViewerController")
def start_slideshow(ctx, fv, interval: float = 3.0, loop: bool = True):
    fv.start_autoplay(
        interval_ms=int(float(interval) * 1000),
        loop=bool(loop),
    )


@require(fv="FileViewerController")
def stop_slideshow(ctx, fv):
    fv.stop_autoplay()


@require(provider="FileListProvider")
def set_list_sync(ctx, provider):
    provider.set_mode(ListMode.SYNC)
    Command.set_action_group_current(GROUP_LIST_MODE, 'fv.list_sync', save=False)


@require(provider="FileListProvider")
def set_list_fix(ctx, provider):
    provider.set_mode(ListMode.FIX)
    Command.set_action_group_current(GROUP_LIST_MODE, 'fv.list_fix', save=False)


@require(provider="FileListProvider")
def set_list_dir(ctx, provider):
    provider.set_mode(ListMode.DIR)
    Command.set_action_group_current(GROUP_LIST_MODE, 'fv.list_dir', save=False)


class FileViewerCommands(ActionKit.MenuBase):
    NAME = "FileViewer"
    PRIORITY = 55

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
                    ActionKit.Param(name="interval", value=3.0, min_value=0.5, max_value=60.0),
                    ActionKit.Param(name="loop", value=True),
                ],
            ),
            ActionKit.Command(
                path="fv.start_slideshow",
                display="Start Slideshow",
                func=start_slideshow,
                hidden=True,
                params=[
                    ActionKit.Param(name="interval", value=3.0, min_value=0.5, max_value=60.0),
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
            ":List Mode",
            ActionKit.Command(
                path="List Mode/fv.list_sync",
                display="Sync",
                func=set_list_sync,
                checkable=True,
                default_checked=True,
                action_group=GROUP_LIST_MODE,
            ),
            ActionKit.Command(
                path="List Mode/fv.list_fix",
                display="Fixed",
                func=set_list_fix,
                checkable=True,
                action_group=GROUP_LIST_MODE,
            ),
            ActionKit.Command(
                path="List Mode/fv.list_dir",
                display="Directory",
                func=set_list_dir,
                checkable=True,
                action_group=GROUP_LIST_MODE,
            ),
            "-",
        ]
