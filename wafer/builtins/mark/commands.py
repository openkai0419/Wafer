from __future__ import annotations

from ...core.commands.bridge import ActionKit
from ...core.commands.command.require import require
from ...core.lang.manager import t
from ...utils.logs import AppLogger
from ...utils.notifier import Notifier
from . import dialogs
from .registry import MarkRegistry


def _ctx_paths(ctx) -> list[str]:
    paths = ctx.get("paths")
    if isinstance(paths, list) and paths:
        return [str(p) for p in paths if p]
    p = ctx.get("path")
    return [str(p)] if p else []


def _resolve_id(name: str) -> str | None:
    if not name:
        return None
    reg = MarkRegistry.instance()
    if reg.get(name) is not None:
        return name
    for m in reg.marks():
        if m.name == name:
            return m.id
    lowered = name.lower()
    for m in reg.marks():
        if m.name.lower() == lowered or m.id.lower() == lowered:
            return m.id
    return None


@require(w="MainWindow")
def _send_batch(ctx, paths, upserts, deletes, *, w):
    from ...app.viewer.preview.tag_edit_service import TagEditService

    db = w.database_name or ""
    if not db:
        AppLogger.warning("[Mark] no active database")
        return
    TagEditService.instance().submit(paths, upserts, deletes, db=db, scope="meta_info")


def add_mark(ctx, name: str = ""):
    paths = _ctx_paths(ctx)
    mark_id = _resolve_id(name)
    if not paths or mark_id is None:
        if name and mark_id is None:
            Notifier.warning(t("Unknown mark: {name}", name=name))
        return
    _send_batch(ctx, paths, [(MarkRegistry.key(mark_id), "1", False)], [])


def remove_mark(ctx, name: str = ""):
    paths = _ctx_paths(ctx)
    mark_id = _resolve_id(name)
    if not paths or mark_id is None:
        if name and mark_id is None:
            Notifier.warning(t("Unknown mark: {name}", name=name))
        return
    _send_batch(ctx, paths, [], [MarkRegistry.key(mark_id)])


def toggle_mark(ctx, name: str = ""):
    paths = _ctx_paths(ctx)
    mark_id = _resolve_id(name)
    if not paths or mark_id is None:
        if name and mark_id is None:
            Notifier.warning(t("Unknown mark: {name}", name=name))
        return
    from ...core.commands.binding.instance_registry import InstanceRegistry

    svc = InstanceRegistry.instance().get_one("MarkOverlayService")
    key = MarkRegistry.key(mark_id)
    has_any_unmarked = svc is None or any(mark_id not in svc.marks_for(p) for p in paths)
    if has_any_unmarked:
        _send_batch(ctx, paths, [(key, "1", False)], [])
    else:
        _send_batch(ctx, paths, [], [key])


def clear_marks(ctx):
    paths = _ctx_paths(ctx)
    if not paths:
        return
    keys = [MarkRegistry.key(mid) for mid in MarkRegistry.instance().ids()]
    if not keys:
        return
    _send_batch(ctx, paths, [], keys)


@require(w="MainWindow")
def set_color(ctx, name: str = "", *, w):
    mark_id = _resolve_id(name)
    if mark_id is None:
        Notifier.warning(t("Unknown mark: {name}", name=name))
        return
    dialogs.prompt_pick_color(w, mark_id)


@require(w="MainWindow")
def define_mark(ctx, *, w):
    dialogs.prompt_new_mark(w)


def remove_mark_def(ctx, name: str = ""):
    mark_id = _resolve_id(name)
    if mark_id is None:
        return
    MarkRegistry.instance().remove(mark_id)


@require(w="MainWindow")
def rename_mark(ctx, name: str = "", *, w):
    mark_id = _resolve_id(name)
    if mark_id is None:
        return
    dialogs.prompt_rename_mark(w, mark_id)


def _mark_name_choices() -> list[str]:
    return [m.name for m in MarkRegistry.instance().marks()]


class MarkCommands(ActionKit.MenuBase):
    NAME = "File"
    PRIORITY = 35

    @classmethod
    def commands(cls):
        return [
            "Mark/:Mark",
            ActionKit.Command(
                path="Mark/mark.toggle",
                display=t("Toggle Mark"),
                params=[ActionKit.Param(name="name", value=_mark_name_choices, description=t("Mark name"), required=True)],
                func=toggle_mark,
            ),
            ActionKit.Command(
                path="Mark/mark.add",
                display=t("Add Mark"),
                params=[ActionKit.Param(name="name", value=_mark_name_choices, description=t("Mark name"), required=True)],
                func=add_mark,
            ),
            ActionKit.Command(
                path="Mark/mark.remove",
                display=t("Remove Mark"),
                params=[ActionKit.Param(name="name", value=_mark_name_choices, description=t("Mark name"), required=True)],
                func=remove_mark,
            ),
            ActionKit.Command(path="Mark/mark.clear", display=t("Clear All Marks"), func=clear_marks),
            "Mark/-",
            ActionKit.Command(
                path="Mark/mark.define",
                display=t("Define New Mark..."),
                func=define_mark,
            ),
            ActionKit.Command(
                path="Mark/mark.rename",
                display=t("Rename Mark..."),
                params=[
                    ActionKit.Param(name="name", value=_mark_name_choices, description=t("Mark name"), required=True),
                ],
                func=rename_mark,
            ),
            ActionKit.Command(
                path="Mark/mark.set_color",
                display=t("Set Mark Color..."),
                params=[
                    ActionKit.Param(name="name", value=_mark_name_choices, description=t("Mark name"), required=True),
                ],
                func=set_color,
            ),
            ActionKit.Command(
                path="Mark/mark.remove_def",
                display=t("Remove Mark Definition"),
                params=[ActionKit.Param(name="name", value=_mark_name_choices, description=t("Mark name"), required=True)],
                func=remove_mark_def,
            ),
        ]
