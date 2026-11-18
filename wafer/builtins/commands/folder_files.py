import os
import stat
from collections.abc import Sequence

from wafer.builtins.filters import DirectoryFilter
from wafer.builtins.sorts import NoSort
from wafer.core.common.paths import child_prefix, normalize_path
from wafer.core.db.db_utils import open_readonly
from wafer.core.db.query import ALL_PATHS_SQL, FileSearchEngine
from wafer.core.logs import AppLogger
from wafer.plugin.query.composer import SearchComposer


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


def is_real_folder(entry: os.DirEntry) -> bool:
    return entry.is_dir(follow_symlinks=False) and getattr(entry.stat(follow_symlinks=False), "st_reparse_tag", 0) != stat.IO_REPARSE_TAG_MOUNT_POINT


def disk_files(folders: Sequence[str], recursive: bool) -> list[str]:
    found: dict[str, None] = {}
    pending = list(dict.fromkeys(normalize_path(folder) for folder in folders))
    walked: set[str] = set()
    while pending:
        folder = pending.pop()
        if folder in walked:
            continue
        walked.add(folder)
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    if not entry.is_dir():
                        found[normalize_path(entry.path)] = None
                    elif recursive and is_real_folder(entry):
                        pending.append(normalize_path(entry.path))
        except OSError as exc:
            AppLogger.warning(f"[Files in Folder] Skipped a folder that cannot be read: {normalize_path(folder)} ({exc})")
    return list(found)
