import posixpath
from collections.abc import Sequence

from wafer.builtins.filters import DirectoryFilter
from wafer.builtins.sorts import NoSort
from wafer.core.common.paths import normalize_path
from wafer.core.db.query import FileSearchEngine
from wafer.plugin.query.composer import SearchComposer


def query_sources(db_path: str, filter_entries: Sequence[tuple]) -> list[str]:
    engine = FileSearchEngine(db_path)
    try:
        _paths, sources, _aspects = SearchComposer().execute(engine, list(filter_entries), NoSort, True)
    finally:
        engine.close()
    return list(dict.fromkeys(sources))


def folder_sources(
    db_path: str, folders: Sequence[str], recursive: bool, filter_entries: Sequence[tuple] = ()
) -> list[str]:
    entries = [*filter_entries, (DirectoryFilter, {"directories": list(folders), "include_subfolders": True}, None)]
    sources = query_sources(db_path, entries)
    if recursive:
        return sources
    direct = {normalize_path(folder) for folder in folders}
    return [source for source in sources if posixpath.dirname(source) in direct]
