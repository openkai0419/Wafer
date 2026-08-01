from __future__ import annotations

from ...core.commands.bridge import ActionKit
from ...core.db.dispatch import DB_SCOPE_ALL
from ...core.db.recollect import Recollect
from ...plugin.collector.handler import collector_resolver
from ...plugin.parser.handler import parser_resolver
from ...ui.dialogs import ConfirmDialog
from ...utils.notifier import Notifier
from ...utils.paths import containing_dir, normalize_path
from ...utils.virtual_paths import is_virtual_path
from .file import _ctx_sources


def _current_db(ctx) -> str | None:
    w = ctx.get_instance("MainWindow") if hasattr(ctx, "get_instance") else None
    return getattr(w, "database_name", None) if w else None


def _folder_prefixes(ctx) -> list[str]:
    get = ctx.get if hasattr(ctx, "get") else lambda *_: None
    raw = get("sources") or get("paths") or ([get("path")] if get("path") else [])
    folders = (normalize_path(containing_dir(p)) for p in raw if p and not is_virtual_path(str(p)))
    return list(dict.fromkeys(folders))


def _collector_prefix_choices() -> list[str]:
    return sorted(set(collector_resolver.names()) | set(parser_resolver.names()))


_SCOPE_LABEL = {"files": "selected file(s)", "folder": "selected folder(s)", "db": "database"}


def _confirm(ctx, *, scope, op, all_db, prefix, count, delete=False) -> bool:
    parent = None
    if hasattr(ctx, "get_instance"):
        parent = ctx.get_instance("ContentViewerWidget") or ctx.get_instance("GridView") or ctx.get_instance("FolderTree")
    where = "ALL databases" if all_db else "this database"
    target = _SCOPE_LABEL[scope]
    if scope in ("files", "folder"):
        target = f"{count} {target}"
    if op == "forget":
        title, ok = "Forget & Recollect", "Forget"
        body = f"Delete all collected data for {target} in {where}, then re-collect from scratch?"
    elif op == "reset_prefix":
        title, ok = "Recollect", "Recollect"
        subject = f"collector '{prefix}'"
        body = f"Delete existing data and re-run {subject} for {target} in {where}?" if delete else f"Re-run {subject} for {target} in {where}?"
    else:
        title, ok = "Recollect All", "Recollect"
        body = f"Delete existing data and re-run ALL collectors for {target} in {where}?" if delete else f"Re-run ALL collectors for {target} in {where}?"
    if all_db:
        body = "[All Databases]\n" + body
    return ConfirmDialog.ask(body, title=title, buttons=(ok, "Cancel"), parent=parent) == ok


def _execute(ctx, *, scope, op, all_db=False, prefix=None, delete=False):
    if op == "reset_prefix" and not prefix:
        return
    db_scope = DB_SCOPE_ALL if all_db else _current_db(ctx)
    if not all_db and not db_scope:
        Notifier.warning("No active database")
        return
    sources = prefixes = None
    if scope == "files":
        sources = _ctx_sources(ctx)
        if not sources:
            return
    elif scope == "folder":
        prefixes = _folder_prefixes(ctx)
        if not prefixes:
            return
    count = len(sources or prefixes or [])
    if not _confirm(ctx, scope=scope, op=op, all_db=all_db, prefix=prefix, count=count, delete=delete):
        return
    if op == "forget":
        if scope == "files":
            Recollect.forget(db_scope=db_scope, sources=sources)
        elif scope == "folder":
            Recollect.forget(db_scope=db_scope, prefixes=prefixes)
        else:
            Recollect.forget(db_scope=db_scope, all=True)
    elif op == "reset_prefix":
        Recollect.reset(db_scope=db_scope, collector=prefix, sources=sources, prefixes=prefixes, delete=delete)
    else:
        names = _collector_prefix_choices()
        if not names:
            Notifier.warning("No collectors registered")
            return
        for name in names:
            Recollect.reset(db_scope=db_scope, collector=name, sources=sources, prefixes=prefixes, delete=delete)
    Notifier.info("Recollect requested")


def files_reset_prefix(ctx, prefix: str = "", delete: bool = False):
    _execute(ctx, scope="files", op="reset_prefix", prefix=prefix, delete=delete)


def files_reset_all(ctx, delete: bool = False):
    _execute(ctx, scope="files", op="reset_all", delete=delete)


def files_forget(ctx):
    _execute(ctx, scope="files", op="forget")


def folder_reset_prefix(ctx, prefix: str = "", delete: bool = False):
    _execute(ctx, scope="folder", op="reset_prefix", prefix=prefix, delete=delete)


def folder_reset_all(ctx, delete: bool = False):
    _execute(ctx, scope="folder", op="reset_all", delete=delete)


def folder_forget(ctx):
    _execute(ctx, scope="folder", op="forget")


def db_reset_prefix(ctx, prefix: str = "", delete: bool = False):
    _execute(ctx, scope="db", op="reset_prefix", prefix=prefix, delete=delete)


def db_reset_all(ctx, delete: bool = False):
    _execute(ctx, scope="db", op="reset_all", delete=delete)


def db_forget(ctx):
    _execute(ctx, scope="db", op="forget")


def all_db_reset_prefix(ctx, prefix: str = "", delete: bool = False):
    _execute(ctx, scope="db", op="reset_prefix", all_db=True, prefix=prefix, delete=delete)


def all_db_reset_all(ctx, delete: bool = False):
    _execute(ctx, scope="db", op="reset_all", all_db=True, delete=delete)


def all_db_forget(ctx):
    _execute(ctx, scope="db", op="forget", all_db=True)


def _prefix_param():
    return [ActionKit.Param(name="prefix", value=_collector_prefix_choices, description="Collector prefix", required=True)]


def _delete_param():
    return [ActionKit.Param(name="delete", value=False, description="Delete existing data before recollect")]


class FileRecollectCommands(ActionKit.MenuBase):
    NAME = "File"
    SCOPE = "*"
    PRIORITY = 12

    @classmethod
    def commands(cls):
        return [
            "Recollect/Selected Files/:Selected Files",
            ActionKit.Command(path="Recollect/Selected Files/file.recollect.files.reset_prefix", display="Specific collector", params=_prefix_param() + _delete_param(), func=files_reset_prefix),
            ActionKit.Command(path="Recollect/Selected Files/file.recollect.files.reset_all", display="All collector", params=_delete_param(), func=files_reset_all),
            ActionKit.Command(path="Recollect/Selected Files/file.recollect.files.forget", display="Delete and Recollect", func=files_forget),
            "Recollect/Selected Folder/:Selected Folder",
            ActionKit.Command(path="Recollect/Selected Folder/file.recollect.folder.reset_prefix", display="Specific collector", params=_prefix_param() + _delete_param(), func=folder_reset_prefix),
            ActionKit.Command(path="Recollect/Selected Folder/file.recollect.folder.reset_all", display="All collector", params=_delete_param(), func=folder_reset_all),
            ActionKit.Command(path="Recollect/Selected Folder/file.recollect.folder.forget", display="Delete and Recollect", func=folder_forget),
            "Recollect/This Database/:This Database",
            ActionKit.Command(path="Recollect/This Database/file.recollect.db.reset_prefix", display="Specific collector", params=_prefix_param() + _delete_param(), func=db_reset_prefix),
            ActionKit.Command(path="Recollect/This Database/file.recollect.db.reset_all", display="All collector", params=_delete_param(), func=db_reset_all),
            ActionKit.Command(path="Recollect/This Database/file.recollect.db.forget", display="Delete and Recollect", func=db_forget),
            "Recollect/All Databases/:All Databases",
            ActionKit.Command(path="Recollect/All Databases/file.recollect.all_db.reset_prefix", display="Specific collector", params=_prefix_param() + _delete_param(), func=all_db_reset_prefix),
            ActionKit.Command(path="Recollect/All Databases/file.recollect.all_db.reset_all", display="All collector", params=_delete_param(), func=all_db_reset_all),
            ActionKit.Command(path="Recollect/All Databases/file.recollect.all_db.forget", display="Delete and Recollect", func=all_db_forget),
        ]
