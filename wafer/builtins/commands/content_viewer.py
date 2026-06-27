from ...core.commands.bridge import ActionKit, Command as BridgeCommand
from ...core.commands.command.require import require
from ...core.commands.binding.instance_registry import InstanceRegistry
from ...app.viewer.preview.file_list_provider import ListMode
from ...utils.notifier import Notifier


GROUP_LIST_MODE = "fv_list_mode"

_CMD_TO_LIST_MODE = {
    "fv.list_sync": ListMode.SYNC,
    "fv.list_fix": ListMode.FIX,
    "fv.list_dir": ListMode.DIR,
}


def _list_mode_checked(cmd_id: str) -> bool:
    provider = InstanceRegistry.instance().get_one("FileListProvider")
    target = _CMD_TO_LIST_MODE.get(cmd_id)
    if provider is None or target is None:
        return False
    return getattr(provider, "mode", None) == target


def _open_contained_files_as_list_checked() -> bool:
    provider = InstanceRegistry.instance().get_one("FileListProvider")
    return bool(getattr(provider, "open_contained_files_as_list", False)) if provider is not None else False


def apply_list_mode(provider, cmd_id: str):
    mode = _CMD_TO_LIST_MODE.get(cmd_id)
    if mode is None:
        return
    provider.set_mode(mode)


def _nav_direction(local_pos, center, axis: str = "left/right", invert: bool = False) -> str:
    mode = str(axis or "left/right").strip().lower()
    dx = local_pos.x() - center.x()
    dy = local_pos.y() - center.y()
    if mode in ("horizontal", "left/right"):
        is_next = dx >= 0
    elif mode in ("vertical", "up/down"):
        is_next = dy >= 0
    else:
        is_next = dx >= 0 if abs(dx) >= abs(dy) else dy >= 0
    if bool(invert):
        is_next = not is_next
    return "next" if is_next else "prev"


@require(fv="FileViewerController")
def next_file(ctx, fv, step: int = 1, loop: bool = False, by_display_count: bool = False):
    fv.navigate_next(step=int(step), loop=bool(loop), by_display_count=bool(by_display_count), origin="command")


@require(fv="FileViewerController")
def prev_file(ctx, fv, step: int = 1, loop: bool = False, by_display_count: bool = False):
    fv.navigate_prev(step=int(step), loop=bool(loop), by_display_count=bool(by_display_count), origin="command")


@require(fv="FileViewerController")
def navigate_file_by_mouse_position(ctx, fv, axis: str = "left/right", invert: bool = False, loop: bool | None = None):
    widget = getattr(ctx, "_widget", None)
    global_pos = getattr(ctx, "global_pos", None)
    if widget is None or global_pos is None or not hasattr(widget, "rect") or not hasattr(widget, "mapFromGlobal"):
        Notifier.warning("Positional navigation requires a bound widget")
        return
    local_pos = widget.mapFromGlobal(global_pos)
    direction = _nav_direction(local_pos, widget.rect().center(), axis=axis, invert=bool(invert))
    if direction == "next":
        BridgeCommand.invoke("fv.next_file", ctx=ctx)
        return
    BridgeCommand.invoke("fv.prev_file", ctx=ctx)


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
    apply_list_mode(provider, "fv.list_sync")


@require(provider="FileListProvider")
def set_list_fix(ctx, provider):
    apply_list_mode(provider, "fv.list_fix")


@require(provider="FileListProvider")
def set_list_dir(ctx, provider):
    apply_list_mode(provider, "fv.list_dir")


@require(provider="FileListProvider")
def toggle_open_contained_files_as_list(ctx, provider):
    provider.set_open_contained_files_as_list(not provider.open_contained_files_as_list)


class FileViewerCommands(ActionKit.MenuBase):
    NAME = "FileViewer"
    PRIORITY = 50

    @classmethod
    def commands(cls):
        return [
            ":List Mode",
            ActionKit.Command(
                path="List Mode/fv.list_sync",
                display="Sync",
                func=set_list_sync,
                action_group=GROUP_LIST_MODE,
                checked=lambda: _list_mode_checked("fv.list_sync"),
            ),
            ActionKit.Command(
                path="List Mode/fv.list_fix",
                display="Fixed",
                func=set_list_fix,
                action_group=GROUP_LIST_MODE,
                checked=lambda: _list_mode_checked("fv.list_fix"),
            ),
            ActionKit.Command(
                path="List Mode/fv.list_dir",
                display="Directory",
                func=set_list_dir,
                action_group=GROUP_LIST_MODE,
                checked=lambda: _list_mode_checked("fv.list_dir"),
            ),
            "-",
            ActionKit.Command(
                path="fv.open_contained_files_as_list",
                display="Open Contained Files as List",
                func=toggle_open_contained_files_as_list,
                checked=_open_contained_files_as_list_checked,
            ),
            "-",
            ":File List",
            ActionKit.Command(
                path="fv.prev_file",
                display="Prev File",
                func=prev_file,
                params=[
                    ActionKit.Param(name="step", value=1),
                    ActionKit.Param(name="loop", value=False),
                    ActionKit.Param(name="by_display_count", value=False),
                ],
            ),
            ActionKit.Command(
                path="fv.next_file",
                display="Next File",
                func=next_file,
                params=[
                    ActionKit.Param(name="step", value=1),
                    ActionKit.Param(name="loop", value=False),
                    ActionKit.Param(name="by_display_count", value=False),
                ],
            ),
            ActionKit.Command(
                path="fv.navigate_file_by_mouse_position",
                display="Navigate by Mouse Position",
                func=navigate_file_by_mouse_position,
                params=[
                    ActionKit.Param(name="axis", value=("left/right", "up/down"), default="left/right"),
                    ActionKit.Param(name="invert", value=False),
                ],
            ),
            "-",
            ActionKit.Command(
                path="fv.toggle_slideshow",
                display="Slideshow",
                func=toggle_slideshow,
                checked=lambda: getattr(InstanceRegistry.instance().get_one("FileViewerController"), "autoplay_active", False),
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
        ]
