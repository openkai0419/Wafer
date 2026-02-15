from PySide6 import QtCore, QtGui, QtWidgets

from ...actions.bridge import Kit


def _get_imgv(ctx):
    return ctx.get_instance("ImageView")


def fit_in_view(ctx, padding: float = 0.0, mode: str | None = None):
    gv = _get_imgv(ctx)
    gv.fit_in_view(padding=float(padding), mode=mode)

def toggle_fit_mode(ctx):
    gv = _get_imgv(ctx)
    gv.toggle_fit_mode()
    gv.fit_in_view(padding=0.0)


def _zoom(gv, *, base: float, steps: int, pos=None):
    if getattr(gv, "_pix_item", None) is None:
        return
    s = int(steps)
    if s <= 0:
        return
    factor = float(base) ** float(s)
    gv.zoom_at(factor, pos)


def zoom_in(ctx, base: float = 1.1):
    gv = _get_imgv(ctx)
    _zoom(gv, base=float(base), steps=int(ctx.get("wheel_steps")), pos=ctx.pos)


def zoom_out(ctx, base: float = 1.1):
    gv = _get_imgv(ctx)
    _zoom(gv, base=float(base) ** -1.0, steps=int(ctx.get("wheel_steps")), pos=ctx.pos)


def _pan_start(ctx):
    gv = _get_imgv(ctx)
    gv._is_panning = True
    gv._last_pos = ctx.pos
    gv.setCursor(QtCore.Qt.CursorShape.ClosedHandCursor)


def _pan_move(ctx):
    gv = _get_imgv(ctx)
    if not getattr(gv, "_is_panning", False):
        return
    cur = ctx.pos
    dv = cur - gv._last_pos
    gv._last_pos = cur
    gv.pan_by(dv.x(), dv.y())


def _pan_end(ctx):
    gv = _get_imgv(ctx)
    if not getattr(gv, "_is_panning", False):
        return
    gv._is_panning = False
    gv.setCursor(QtCore.Qt.CursorShape.ArrowCursor)

class ImageViewCommands(Kit.MenuBase):
    prefix = "ImageView"
    commands = [
        ":ImageView",
        Kit.Command(
            path="imgv.fit_in_view",
            display="Fit In View",
            func=fit_in_view,
            params=[
                Kit.Param(name="padding", value=0.0),
                Kit.Param(name="mode", value=("contain", "cover"), default=None),
            ],
        ),
        Kit.Command(path="imgv.toggle_fit_mode", display="Toggle Fit Mode", func=toggle_fit_mode),
        "-",
        Kit.Command(
            path="imgv.zoom_in",
            display="Zoom In",
            func=zoom_in,
            params=[Kit.Param(name="base", value=1.1)],
        ),
        Kit.Command(
            path="imgv.zoom_out",
            display="Zoom Out",
            func=zoom_out,
            params=[Kit.Param(name="base", value=1.1)],
        ),
    ]


class ImageViewDragCommands(Kit.DragMenuBase):
    prefix = "ImageView"
    commands = [
        Kit.Command(
            path="imgv.pan",
            display="Pan",
            category="drag",
            drag_callbacks={"start": _pan_start, "move": _pan_move, "end": _pan_end},
            target_widgets=["ImageView"],
        ),
    ]
