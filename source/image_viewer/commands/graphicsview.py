from PySide6 import QtCore, QtGui, QtWidgets

from ...actions.bridge import Kit


def _require_gv(ctx):
    if ctx is None:
        raise RuntimeError("GraphicsView not found: ctx is None")
    get = getattr(ctx, "get", None)
    w = get("widget") if callable(get) else None
    if w is not None and hasattr(w, "fit_in_view"):
        return w
    gw = getattr(ctx, "get_widget", None)
    if callable(gw):
        w = gw("GraphicsView")
        if w is not None:
            return w
    raise RuntimeError(f"GraphicsView not found in ctx: {type(ctx).__name__}")


def reset_view(ctx):
    gv = _require_gv(ctx)
    gv.setTransform(QtGui.QTransform())
    gv.centerOn(gv.sceneRect().center())
    gv.fit_in_view(padding=0.0)


def fit_in_view(ctx, padding: float = 0.0, mode: str | None = None):
    gv = _require_gv(ctx)
    gv.fit_in_view(padding=float(padding), mode=mode)

def toggle_fit_mode(ctx):
    gv = _require_gv(ctx)
    gv.toggle_fit_mode()
    gv.fit_in_view(padding=0.0)


def _zoom(gv, *, base: float, steps: int):
    if not hasattr(gv, "_pix_item"):
        return
    if getattr(gv, "_pix_item", None) is None:
        return
    s = int(steps)
    if s <= 0:
        return
    before = gv._current_scale()
    gv._set_scale(float(base) ** float(s))
    gv._clamp_scale()
    after = gv._current_scale()
    if before != after:
        gv.zoomChanged.emit(after)


def zoom_in(ctx, base: float = 1.1):
    gv = _require_gv(ctx)
    _zoom(gv, base=float(base), steps=int(ctx.get("wheel_steps")))


def zoom_out(ctx, base: float = 1.1):
    gv = _require_gv(ctx)
    _zoom(gv, base=float(base) ** -1.0, steps=int(ctx.get("wheel_steps")))


def _pan_start(ctx):
    gv = _require_gv(ctx)
    gv._is_panning = True
    gv._last_pos = ctx.pos
    gv.setCursor(QtCore.Qt.CursorShape.ClosedHandCursor)
    gv.setDragMode(QtWidgets.QGraphicsView.NoDrag)


def _pan_move(ctx):
    gv = _require_gv(ctx)
    if not getattr(gv, "_is_panning", False):
        return
    cur = ctx.pos
    dv = cur - gv._last_pos
    gv._last_pos = cur
    gv.horizontalScrollBar().setValue(gv.horizontalScrollBar().value() - dv.x())
    gv.verticalScrollBar().setValue(gv.verticalScrollBar().value() - dv.y())


def _pan_end(ctx):
    gv = _require_gv(ctx)
    if not getattr(gv, "_is_panning", False):
        return
    gv._is_panning = False
    gv.setCursor(QtCore.Qt.CursorShape.ArrowCursor)

class GraphicsViewCommands(Kit.MenuBase):
    prefix = "GraphicsView"

    commands = [
        ":GraphicsView",
        Kit.Command(path="gv.reset_view", display="Reset View", func=reset_view),
        Kit.Command(
            path="gv.fit_in_view",
            display="Fit In View",
            func=fit_in_view,
            params=[
                Kit.Param(name="padding", value=0.0),
                Kit.Param(name="mode", value=("contain", "cover"), default=None),
            ],
        ),
        Kit.Command(path="gv.toggle_fit_mode", display="Toggle Fit Mode", func=toggle_fit_mode),
        "-",
        Kit.Command(
            path="gv.zoom_in",
            display="Zoom In",
            func=zoom_in,
            params=[Kit.Param(name="base", value=1.1)],
        ),
        Kit.Command(
            path="gv.zoom_out",
            display="Zoom Out",
            func=zoom_out,
            params=[Kit.Param(name="base", value=1.1)],
        ),
    ]


class GraphicsViewDragCommands(Kit.DragMenuBase):
    prefix = "GraphicsView"

    commands = [
        Kit.Command(
            path="gv.pan",
            display="Pan",
            category="drag",
            drag_callbacks={"start": _pan_start, "move": _pan_move, "end": _pan_end},
            target_widgets=["GraphicsView"],
        ),
    ]
