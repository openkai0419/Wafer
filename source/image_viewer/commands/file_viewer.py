from ...actions.bridge import Kit


def _get_viewer_widget(ctx):
    return ctx.get_instance("ViewerWidget")


def _get_viewer_items(ctx):
    return ctx.get_instance("ViewerItems")


def _ensure_current_initialized(items, viewer) -> bool:
    if items is None or viewer is None:
        return False
    if items.count() <= 0:
        return False
    cur = items.current_index()
    if cur is None and getattr(viewer, "path", None):
        i = items.index_of_path(str(viewer.path))
        if i is not None:
            items.set_current_index(i)
            cur = i
    if cur is None:
        items.set_current_index(0)
        p = items.path_at(items.current_index())
        if p:
            viewer.set_path(p)
        return False
    return True


def next_file(ctx, step: int = 1, loop: bool = False):
    viewer = _get_viewer_widget(ctx)
    items = _get_viewer_items(ctx)
    if not _ensure_current_initialized(items, viewer):
        return
    p = items.move_current_next(step=int(step), loop=bool(loop))
    if p:
        viewer.set_path(p)


def prev_file(ctx, step: int = 1, loop: bool = False):
    viewer = _get_viewer_widget(ctx)
    items = _get_viewer_items(ctx)
    if not _ensure_current_initialized(items, viewer):
        return
    p = items.move_current_prev(step=int(step), loop=bool(loop))
    if p:
        viewer.set_path(p)


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
