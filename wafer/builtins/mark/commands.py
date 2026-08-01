from __future__ import annotations

import uuid

from ...core.commands.binding.instance_registry import InstanceRegistry
from ...core.db.dispatch import send_to_db_scope
from ...core.db.key_value import normalize_data_scope
from ...core.lang.manager import t
from ...plugin import CommandMeta, CommandParam, MenuGroup, require
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
def _send_batch(ctx, paths, upserts, deletes, *, w, scope: str):
    from ...ui.panel.tag_edit_service import TagEditService

    db = w.database_name or ""
    if not db:
        AppLogger.warning("[Mark] no active database")
        return
    TagEditService.instance().submit(paths, upserts, deletes, db=db, scope=scope)


def add_mark(ctx, name: str = ""):
    paths = _ctx_paths(ctx)
    mark_id = _resolve_id(name)
    if not paths or mark_id is None:
        if name and mark_id is None:
            Notifier.warning(t("Unknown mark: {name}", name=name))
        return
    scope = MarkRegistry.instance().scope_of(mark_id)
    _send_batch(ctx, paths, [(MarkRegistry.key(mark_id), "1", False)], [], scope=scope)


def remove_mark(ctx, name: str = ""):
    paths = _ctx_paths(ctx)
    mark_id = _resolve_id(name)
    if not paths or mark_id is None:
        if name and mark_id is None:
            Notifier.warning(t("Unknown mark: {name}", name=name))
        return
    _send_batch(ctx, paths, [], [MarkRegistry.key(mark_id)], scope="*")


def toggle_mark(ctx, name: str = ""):
    paths = _ctx_paths(ctx)
    mark_id = _resolve_id(name)
    if not paths or mark_id is None:
        if name and mark_id is None:
            Notifier.warning(t("Unknown mark: {name}", name=name))
        return
    from .overlay import MarkBadgeOverlayPlugin

    host = InstanceRegistry.instance().get_one("GridOverlayHost")
    key = MarkRegistry.key(mark_id)
    has_any_unmarked = host is None or any(mark_id not in host.values_for(MarkBadgeOverlayPlugin.NAME, p) for p in paths)
    if has_any_unmarked:
        scope = MarkRegistry.instance().scope_of(mark_id)
        _send_batch(ctx, paths, [(key, "1", False)], [], scope=scope)
    else:
        _send_batch(ctx, paths, [], [key], scope="*")


def clear_marks(ctx):
    paths = _ctx_paths(ctx)
    if not paths:
        return
    keys = [MarkRegistry.key(mid) for mid in MarkRegistry.instance().ids()]
    if not keys:
        return
    _send_batch(ctx, paths, [], keys, scope="*")


@require(w="MainWindow")
def set_color(ctx, name: str = "", *, w):
    mark_id = _resolve_id(name)
    if mark_id is None:
        Notifier.warning(t("Unknown mark: {name}", name=name))
        return
    dialogs.prompt_pick_color(w, mark_id)


@require(w="MainWindow")
def set_shape(ctx, name: str = "", *, w):
    mark_id = _resolve_id(name)
    if mark_id is None:
        Notifier.warning(t("Unknown mark: {name}", name=name))
        return
    dialogs.prompt_pick_shape(w, mark_id)


@require(w="MainWindow")
def define_mark(ctx, *, w):
    dialogs.prompt_new_mark(w)


def remove_mark_def(ctx, name: str = ""):
    mark_id = _resolve_id(name)
    if mark_id is None:
        return
    MarkRegistry.instance().remove(mark_id)


def convert_mark_scope(ctx, name: str = "", scope: str = "", db_scope: str = "*"):
    mark_id = _resolve_id(name)
    if mark_id is None:
        if name:
            Notifier.warning(t("Unknown mark: {name}", name=name))
        return
    target_scope = normalize_data_scope(scope or MarkRegistry.instance().scope_of(mark_id))
    MarkRegistry.instance().set_scope(mark_id, target_scope)
    node = InstanceRegistry.instance().resolve_node()
    if node is None:
        AppLogger.warning("[Mark] no IPC node for scope conversion")
        return
    key = MarkRegistry.key(mark_id)
    sent = send_to_db_scope(
        node,
        "kv.convert_scope",
        {"key": key, "to_scope": target_scope, "request_id": uuid.uuid4().hex},
        db_scope=db_scope or "*",
    )
    AppLogger.info(f"[Mark] Requested scope conversion key={key} to={target_scope} db_scope={db_scope or '*'} sent={sent}")


@require(w="MainWindow")
def rename_mark(ctx, name: str = "", *, w):
    mark_id = _resolve_id(name)
    if mark_id is None:
        return
    dialogs.prompt_rename_mark(w, mark_id)


def _mark_name_choices() -> list[str]:
    return [m.name for m in MarkRegistry.instance().marks()]


class MarkCommands(MenuGroup):
    NAME = "File"
    DEFAULT_ENABLED = True
    PRIORITY = 35

    @classmethod
    def commands(cls):
        return [
            "Mark/:Mark",
            CommandMeta(
                path="Mark/mark.toggle",
                display=t("Toggle Mark"),
                params=[CommandParam(name="name", value=_mark_name_choices, description=t("Mark name"), required=True)],
                func=toggle_mark,
            ),
            CommandMeta(
                path="Mark/mark.add",
                display=t("Add Mark"),
                params=[CommandParam(name="name", value=_mark_name_choices, description=t("Mark name"), required=True)],
                func=add_mark,
            ),
            CommandMeta(
                path="Mark/mark.remove",
                display=t("Remove Mark"),
                params=[CommandParam(name="name", value=_mark_name_choices, description=t("Mark name"), required=True)],
                func=remove_mark,
            ),
            CommandMeta(path="Mark/mark.clear", display=t("Clear All Marks"), func=clear_marks),
            "Mark/-",
            CommandMeta(
                path="Mark/mark.define",
                display=t("Define New Mark..."),
                func=define_mark,
            ),
            CommandMeta(
                path="Mark/mark.rename",
                display=t("Rename Mark..."),
                params=[
                    CommandParam(name="name", value=_mark_name_choices, description=t("Mark name"), required=True),
                ],
                func=rename_mark,
            ),
            CommandMeta(
                path="Mark/mark.set_color",
                display=t("Set Mark Color..."),
                params=[
                    CommandParam(name="name", value=_mark_name_choices, description=t("Mark name"), required=True),
                ],
                func=set_color,
            ),
            CommandMeta(
                path="Mark/mark.set_shape",
                display=t("Set Mark Shape..."),
                params=[
                    CommandParam(name="name", value=_mark_name_choices, description=t("Mark name"), required=True),
                ],
                func=set_shape,
            ),
            CommandMeta(
                path="Mark/mark.remove_def",
                display=t("Remove Mark Definition"),
                params=[CommandParam(name="name", value=_mark_name_choices, description=t("Mark name"), required=True)],
                func=remove_mark_def,
            ),
            CommandMeta(
                path="Mark/mark.convert_scope",
                display=t("Save Mark Scope and Convert"),
                params=[
                    CommandParam(name="name", value=_mark_name_choices, description=t("Mark name"), required=True),
                    CommandParam(name="scope", value=["meta_info", "tag"], description=t("Storage scope"), required=True),
                    CommandParam(name="db_scope", value="*", description=t("Database scope")),
                ],
                func=convert_mark_scope,
            ),
        ]
