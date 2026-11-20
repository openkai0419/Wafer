import os
from collections.abc import Sequence
from typing import Protocol

from wafer.builtins.filters import DirectoryFilter
from wafer.builtins.sorts import NoSort
from wafer.core.common.folder_scan import JunctionFilter
from wafer.core.common.paths import child_prefix, normalize_path
from wafer.core.db.db_utils import open_readonly
from wafer.core.db.query import ALL_PATHS_SQL, FileSearchEngine
from wafer.core.logs import AppLogger
from wafer.plugin.query.composer import SearchComposer


class Cancellable(Protocol):
    def is_cancelled(self) -> bool: ...


def narrows(filter_entries: Sequence[tuple]) -> bool:
    entries = list(filter_entries)
    if any(filter_cls.has_post_filter() for filter_cls, _params, _op in entries):
        return True
    path_sql, _bind = SearchComposer.compose_path_query(FileSearchEngine(""), entries)
    return path_sql != ALL_PATHS_SQL


def stored_sources(db_path: str) -> list[str]:
    if not os.path.exists(db_path):
        return []
    conn = open_readonly(db_path)
    try:
        return [row[0] for row in conn.execute("SELECT source FROM sources")]
    finally:
        conn.close()


def composed_sources(db_path: str, filter_entries: Sequence[tuple]) -> list[str]:
    engine = FileSearchEngine(db_path)
    try:
        _paths, sources, _aspects = SearchComposer().execute(engine, list(filter_entries), NoSort, True)
    finally:
        engine.close()
    return list(dict.fromkeys(sources))


def query_sources(db_path: str, filter_entries: Sequence[tuple]) -> list[str]:
    if narrows(filter_entries):
        return composed_sources(db_path, filter_entries)
    return stored_sources(db_path)


def query_folder_sources(db_path: str, folders: Sequence[str], recursive: bool, filter_entries: Sequence[tuple]) -> list[str]:
    if not os.path.exists(db_path):
        return []
    entries = [*filter_entries, (DirectoryFilter, {"directories": list(folders), "include_subfolders": True}, None)]
    sources = composed_sources(db_path, entries)
    if recursive:
        return sources
    prefixes = {child_prefix(normalize_path(folder)) for folder in folders}
    return [source for source in sources if source[: source.rfind("/") + 1] in prefixes]


def disk_files(folders: Sequence[str], recursive: bool, cancel: Cancellable | None = None) -> list[str]:
    found: dict[str, None] = {}
    pending = list(dict.fromkeys(normalize_path(folder) for folder in folders))
    junctions = JunctionFilter(pending)
    walked: set[str] = set()
    while pending:
        if cancel is not None and cancel.is_cancelled():
            return []
        folder = pending.pop()
        if folder in walked:
            continue
        walked.add(folder)
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    if entry.is_symlink():
                        if entry.is_file():
                            found[normalize_path(entry.path)] = None
                    elif not entry.is_dir(follow_symlinks=False):
                        found[normalize_path(entry.path)] = None
                    elif recursive and not junctions.skips(entry):
                        pending.append(normalize_path(entry.path))
        except FileNotFoundError:
            AppLogger.warning(f"[Files in Folder] Skipped a folder that no longer exists: {normalize_path(folder)}")
        except OSError as exc:
            AppLogger.warning(f"[Files in Folder] Skipped a folder that could not be listed: {normalize_path(folder)} ({exc})")
    return list(found)
