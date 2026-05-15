from PySide6 import QtCore

from ...core.commands.bridge import ActionKit
from ...core.commands.command.require import require
from ...plugin.viewer.handler import viewer_resolver
from ...utils.logs import AppLogger
from .viewer import ImageViewer


def _zoom(gv, *, base: float, steps: int, pos=None):
    if not gv.has_content():
        return
    s = int(steps)
    if s <= 0:
        return
    factor = float(base) ** float(s)
    gv.zoom_at(factor, pos)


@require(gv="ImageView")
def fit_in_view(ctx, gv, padding: float = 0.0, mode: str | None = None):
    gv.fit_in_view(padding=float(padding), mode=mode)


@require(gv="ImageView")
def toggle_fit_mode(ctx, gv):
    gv.toggle_fit_mode()
    gv.fit_in_view(padding=0.0)


def set_image_spread(ctx, pages: int = 2, direction: str = "right-to-left"):
    image_viewer = viewer_resolver.registry.instance(ImageViewer.NAME)
    if image_viewer is None or not hasattr(image_viewer, "set_image_spread"):
        AppLogger.warning("Image viewer plugin is not available; image spread was not changed")
        return
    image_viewer.set_image_spread(pages=pages, direction=direction)


@require(gv="ImageView")
def zoom_in(ctx, gv, base: float = 1.1):
    _zoom(gv, base=float(base), steps=int(ctx.get("wheel_steps")), pos=ctx.pos)


@require(gv="ImageView")
def zoom_out(ctx, gv, base: float = 1.1):
    _zoom(gv, base=float(base) ** -1.0, steps=int(ctx.get("wheel_steps")), pos=ctx.pos)


@require(gv="ImageView")
def _pan_start(ctx, gv):
    gv._is_panning = True
    gv._last_pos = ctx.pos
    gv.setCursor(QtCore.Qt.CursorShape.ClosedHandCursor)


@require(gv="ImageView")
def _pan_move(ctx, gv):
    if not getattr(gv, "_is_panning", False):
        return
    cur = ctx.pos
    dv = cur - gv._last_pos
    gv._last_pos = cur
    gv.pan_by(dv.x(), dv.y())


@require(gv="ImageView")
def _pan_end(ctx, gv):
    if not getattr(gv, "_is_panning", False):
        return
    gv._is_panning = False
    gv.setCursor(QtCore.Qt.CursorShape.ArrowCursor)


class ImageViewCommands(ActionKit.MenuBase):
    NAME = "FileViewer"
    PRIORITY = 52

    @classmethod
    def commands(cls):
        return [
            ":ImageView",
            ActionKit.Command(
                path="imgv.fit_in_view",
                display="Fit In View",
                func=fit_in_view,
                params=[
                    ActionKit.Param(name="padding", value=0.0),
                    ActionKit.Param(name="mode", value=("contain", "cover"), default=None),
                ],
            ),
            ActionKit.Command(path="imgv.toggle_fit_mode", display="Toggle Fit Mode", func=toggle_fit_mode),
            "-",
            ActionKit.Command(
                path="imgv.zoom_in",
                display="Zoom In",
                func=zoom_in,
                params=[ActionKit.Param(name="base", value=1.1)],
            ),
            ActionKit.Command(
                path="imgv.zoom_out",
                display="Zoom Out",
                func=zoom_out,
                params=[ActionKit.Param(name="base", value=1.1)],
            ),
            ActionKit.Command(
                path="imgv.image_spread",
                display="Image Spread",
                func=set_image_spread,
                params=[
                    ActionKit.Param(name="pages", value=2, min_value=1, max_value=16),
                    ActionKit.Param(name="direction", value=("right-to-left", "left-to-right", "top-to-bottom", "bottom-to-top")),
                ],
            ),
        ]


class ImageViewDragCommands(ActionKit.DragMenuBase):
    NAME = "ImageView"

    @classmethod
    def commands(cls):
        return [
            ActionKit.Command(
                path="imgv.pan",
                display="Pan",
                category="drag",
                drag_callbacks={"start": _pan_start, "move": _pan_move, "end": _pan_end},
                target_widgets=["ImageView"],
            ),
        ]
