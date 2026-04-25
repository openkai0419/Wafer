from __future__ import annotations

from ...core.commands.bridge import ActionKit
from ...core.commands.command.require import require
from ...core.lang.manager import t
from ...utils.logs import AppLogger
from ...utils.notifier import Notifier
from .registry import MarkRegistry


def _ctx_paths(ctx) -> list[str]:
    paths = ctx.get("paths")
    if isinstance(paths, list) and paths:
        return [str(p) for p in paths if p]
    p = ctx.get("path")
    return [str(p)] if p else []


@require(w="MainWindow")
def _send_batch(ctx, paths, upserts, deletes, *, w):
    from ...app.viewer.preview.tag_edit_service import TagEditService

    db = w.database_name or ""
    if not db:
        AppLogger.warning("[Mark] no active database")
        return
    TagEditService.instance().submit(paths, upserts, deletes, db=db)


def add_mark(ctx, mark_id: str):
    paths = _ctx_paths(ctx)
    if not paths or not mark_id:
        return
    key = MarkRegistry.tag_key(mark_id)
    _send_batch(ctx, paths, [(key, "1", False)], [])
    Notifier.info(t("Mark {mark_id} added to {count} file(s)", mark_id=mark_id, count=len(paths)))


def remove_mark(ctx, mark_id: str):
    paths = _ctx_paths(ctx)
    if not paths or not mark_id:
        return
    key = MarkRegistry.tag_key(mark_id)
    _send_batch(ctx, paths, [], [key])
    Notifier.info(t("Mark {mark_id} removed from {count} file(s)", mark_id=mark_id, count=len(paths)))


def toggle_mark(ctx, mark_id: str):
    paths = _ctx_paths(ctx)
    if not paths or not mark_id:
        return
    from ...app.viewer.grid.mark_overlay_service import MarkOverlayService

    svc = MarkOverlayService.instance()
    key = MarkRegistry.tag_key(mark_id)
    has_any_unmarked = False
    if svc is not None:
        for p in paths:
            if mark_id not in svc.marks_for(p):
                has_any_unmarked = True
                break
    else:
        has_any_unmarked = True
    if has_any_unmarked:
        _send_batch(ctx, paths, [(key, "1", False)], [])
    else:
        _send_batch(ctx, paths, [], [key])


def clear_marks(ctx):
    paths = _ctx_paths(ctx)
    if not paths:
        return
    keys = [MarkRegistry.tag_key(mid) for mid in MarkRegistry.instance().ids()]
    if not keys:
        return
    _send_batch(ctx, paths, [], keys)


def set_color(ctx, mark_id: str = "", color: str = ""):
    if not mark_id or not color:
        return
    MarkRegistry.instance().set_color(mark_id, color)


class MarkCommands(ActionKit.MenuBase):
    NAME = "Mark"
    PRIORITY = 35

    @classmethod
    def commands(cls):
        items: list = [":Mark"]
        items += [
            "Toggle/:Toggle Mark",
            *[
                ActionKit.Command(
                    path=f"Toggle/mark.toggle_{mid}",
                    display=f"Toggle Mark {mid}",
                    func=lambda ctx, m=mid: toggle_mark(ctx, m),
                )
                for mid in MarkRegistry.instance().ids()
            ],
            "Add/:Add Mark",
            *[
                ActionKit.Command(
                    path=f"Add/mark.add_{mid}",
                    display=f"Add Mark {mid}",
                    func=lambda ctx, m=mid: add_mark(ctx, m),
                )
                for mid in MarkRegistry.instance().ids()
            ],
            "Remove/:Remove Mark",
            *[
                ActionKit.Command(
                    path=f"Remove/mark.remove_{mid}",
                    display=f"Remove Mark {mid}",
                    func=lambda ctx, m=mid: remove_mark(ctx, m),
                )
                for mid in MarkRegistry.instance().ids()
            ],
            "-",
            ActionKit.Command(path="mark.clear", display="Clear All Marks", func=clear_marks),
            ActionKit.Command(
                path="mark.set_color",
                display="Set Mark Color",
                params=[
                    ActionKit.Param(name="mark_id", value="", description="Mark ID"),
                    ActionKit.Param(name="color", value="", description="Hex color (e.g. #FF0000)"),
                ],
                func=set_color,
            ),
        ]
        return items
