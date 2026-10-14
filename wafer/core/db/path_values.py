from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path


from ..logs import AppLogger
from .db_utils import open_readonly
from .query import STANDARD_KEYS_SOURCES, SYSTEM_FILE_HASH_KEY

SQL_CHUNK_SIZE = 4000
MAX_FILTER_KEYS = 1000


@dataclass(frozen=True, slots=True)
class PathValue:
    text: str
    number: float | None = None


def fetch_path_values(db_path: str | Path | None, paths: list[str], keys: Sequence[str] | None = None) -> dict[str, dict[str, PathValue]]:
    result: dict[str, dict[str, PathValue]] = {}
    key_list = list(dict.fromkeys(keys)) if keys is not None else None
    if key_list is not None and len(key_list) > MAX_FILTER_KEYS:
        key_list = None
    key_marks = ",".join("?" * len(key_list)) if key_list else ""
    meta_clause = f" AND key IN ({key_marks})" if key_list else ""
    tag_clause = f" AND t.key IN ({key_marks})" if key_list else ""
    key_params = key_list or []
    columns = ", ".join(f"s.{name}" for name in STANDARD_KEYS_SOURCES)

    def read(conn: sqlite3.Connection, chunk: list[str], placeholders: str) -> None:
        if key_list is None or key_list:
            for path, key, value, number in conn.execute(f"SELECT path, key, value, value_num FROM meta_info WHERE path IN ({placeholders}){meta_clause}", [*chunk, *key_params]):
                result.setdefault(path, {})[key] = PathValue(value or "", number)
            for path, key, value, number in conn.execute(
                f"SELECT i.path, t.key, t.value, t.value_num FROM tags AS t JOIN sources AS s ON s.file_hash = t.file_hash JOIN files AS i ON i.source = s.source WHERE i.path IN ({placeholders}){tag_clause}",
                [*chunk, *key_params],
            ):
                result.setdefault(path, {})[key] = PathValue(value or "", number)
        for path, name, file_hash, *numbers in conn.execute(
            f"SELECT i.path, i.name, s.file_hash, {columns} FROM files AS i JOIN sources AS s ON s.source = i.source WHERE i.path IN ({placeholders})",
            chunk,
        ):
            entry = result.setdefault(path, {})
            entry["path"] = PathValue(path or "")
            if name is not None:
                entry["name"] = PathValue(str(name))
            if file_hash:
                entry[SYSTEM_FILE_HASH_KEY] = PathValue(str(file_hash))
            for key, value in zip(STANDARD_KEYS_SOURCES, numbers):
                if value is not None:
                    entry[key] = PathValue(str(value), float(value) if isinstance(value, (int, float)) else None)

    _read_chunks(db_path, paths, read, "path values")
    return result


def fetch_sources(db_path: str | Path | None, paths: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}

    def read(conn: sqlite3.Connection, chunk: list[str], placeholders: str) -> None:
        for path, source in conn.execute(f"SELECT path, source FROM files WHERE path IN ({placeholders})", chunk):
            result[path] = source

    _read_chunks(db_path, paths, read, "file sources")
    return result


def _read_chunks(
    db_path: str | Path | None,
    paths: list[str],
    read: Callable[[sqlite3.Connection, list[str], str], None],
    what: str,
) -> None:
    if not db_path or not paths or not os.path.isfile(str(db_path)):
        return
    try:
        conn = open_readonly(db_path)
    except sqlite3.Error as e:
        AppLogger.warning(f"Failed to open database for {what}: {db_path}", exc=e)
        return
    try:
        for start in range(0, len(paths), SQL_CHUNK_SIZE):
            chunk = paths[start : start + SQL_CHUNK_SIZE]
            read(conn, chunk, ",".join("?" * len(chunk)))
    except sqlite3.Error as e:
        AppLogger.warning(f"Failed to read {what}: {db_path}", exc=e)
    finally:
        conn.close()
