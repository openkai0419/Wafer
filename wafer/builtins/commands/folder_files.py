import os
from collections.abc import Sequence

from wafer.builtins.filters import DirectoryFilter
from wafer.builtins.sorts import NoSort
from wafer.core.common.paths import child_prefix, normalize_path
from wafer.core.db.db_utils import open_readonly
from wafer.core.db.query import ALL_PATHS_SQL, FileSearchEngine, path_prefix_condition
from wafer.plugin.query.composer import SearchComposer


def narrows(filter_entries: Sequence[tuple]) -> bool:
    entries = list(filter_entries)
    if any(filter_cls.has_post_filter() for filter_cls, _params, _op in entries):
        return True
    path_sql, _bind = SearchComposer.compose_path_query(FileSearchEngine(""), entries)
    return path_sql != ALL_PATHS_SQL


def stored_sources(db_path: str, folders: Sequence[str] = ()) -> list[str]:
    if not os.path.exists(db_path):
        return []
    conn = open_readonly(db_path)
    try:
        if not folders:
            return [row[0] for row in conn.execute("SELECT source FROM sources")]
        found: dict[str, None] = {}
        for folder in folders:
            condition, bind = path_prefix_condition("source", child_prefix(normalize_path(folder)))
            found.update(dict.fromkeys(row[0] for row in conn.execute(f"SELECT source FROM sources WHERE {condition}", bind)))
        return list(found)
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


def folder_sources(
    db_path: str, folders: Sequence[str], recursive: bool, filter_entries: Sequence[tuple] = ()
) -> list[str]:
    if narrows(filter_entries):
        entries = [*filter_entries, (DirectoryFilter, {"directories": list(folders), "include_subfolders": True}, None)]
        sources = composed_sources(db_path, entries)
    else:
        sources = stored_sources(db_path, folders)
    if recursive:
        return sources
    prefixes = {child_prefix(normalize_path(folder)) for folder in folders}
    return [source for source in sources if source[: source.rfind("/") + 1] in prefixes]
