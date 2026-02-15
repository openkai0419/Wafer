from ...actions.bridge import Kit


def _get_file_model(ctx):
    return ctx.get_instance("FileViewModel")


def _ensure_current_initialized(model) -> bool:
    if model is None:
        return False
    if model.count() <= 0:
        return False
    cur = model.current_index()
    if cur is None:
        model.set_current_index(0)
        return model.current_index() is not None
    return True


def next_file(ctx, step: int = 1, loop: bool = False):
    model = _get_file_model(ctx)
    if not _ensure_current_initialized(model):
        return
    model.move_current_next(step=int(step), loop=bool(loop))


def prev_file(ctx, step: int = 1, loop: bool = False):
    model = _get_file_model(ctx)
    if not _ensure_current_initialized(model):
        return
    model.move_current_prev(step=int(step), loop=bool(loop))


class FileViewerCommands(Kit.MenuBase):
    prefix = "FileViewer"

    commands = [
        ":FileViewer",
        Kit.Command(
            path="fv.prev_file",
            display="Prev File",
            func=prev_file,
            params=[Kit.Param(name="step", value=1), Kit.Param(name="loop", value=False)],
        ),
        Kit.Command(
            path="fv.next_file",
            display="Next File",
            func=next_file,
            params=[Kit.Param(name="step", value=1), Kit.Param(name="loop", value=False)],
        ),
        "-",
    ]
