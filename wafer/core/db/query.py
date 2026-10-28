from __future__ import annotations

import os
import re
import sqlite3
import threading

from ...constants import VIRTUAL_PATH_SEPARATOR
from .db_utils import apply_read_pragmas, escape_like
from .key_value import SCOPE_ALL, SCOPE_META_INFO, SCOPE_TAG, iter_data_scopes, key_prefix_lookup_sql
from ..common.paths import normalize_path
from ..common.virtual_paths import build_virtual_path, is_virtual_path, split_virtual_path
from ..profiling import profiler
from ..logs import AppLogger


SYSTEM_FILE_HASH_KEY = "file_hash"

STANDARD_KEYS_FILES = ("name", "path")
STANDARD_KEYS_SOURCES = ("size", "modified", "created", "collected")
STANDARD_KEYS = STANDARD_KEYS_FILES + STANDARD_KEYS_SOURCES


def standard_key_columns(key: str) -> tuple[str, str, str] | None:
    if key in STANDARD_KEYS_FILES:
        return ("files", "path", key)
    if key in STANDARD_KEYS_SOURCES:
        return (
            "sources AS s JOIN files AS i ON i.source = s.source",
            "i.path",
            f"CAST(s.{key} AS TEXT)",
        )
    return None


KEY_VALUE_TABLES = {
    "meta_info": ("meta_info AS mi", 'mi."key"', 'mi."value"', "mi.path"),
    "tags": ("tags AS t JOIN sources AS s ON s.file_hash = t.file_hash JOIN files AS i ON i.source = s.source", 't."key"', 't."value"', "i.path"),
}


def key_value_path_query(table: str, value_conditions, scope, keys=(), exclude_keys=()) -> tuple[str, list]:
    from_clause, key_col, val_col, path_col = KEY_VALUE_TABLES[table]
    conds, params = [scope.condition(path_col)], []
    if keys:
        conds.append(f"{key_col} IN ({','.join('?' for _ in keys)})")
        params.extend(keys)
    if exclude_keys:
        conds.append(f"{key_col} NOT IN ({','.join('?' for _ in exclude_keys)})")
        params.extend(exclude_keys)
    value_conds, value_params = value_conditions(val_col)
    return f"SELECT {path_col} AS path FROM {from_clause} WHERE {' AND '.join([*conds, *value_conds])}", [*params, *value_params]


def standard_key_path_query(key: str, value_conditions, scope) -> tuple[str | None, list]:
    cols = standard_key_columns(key)
    if cols is None:
        return None, []
    from_clause, path_col, val_col = cols
    value_conds, value_params = value_conditions(val_col)
    return f"SELECT {path_col} AS path FROM {from_clause} WHERE {' AND '.join([scope.condition(path_col), *value_conds])}", value_params


def parse_keywords(keywords, separator: str | None = None, trim: bool = True) -> tuple[list[str], list[str]]:
    if isinstance(keywords, str):
        words = keywords.split(separator) if separator else [keywords]
        if trim:
            words = [w.strip() for w in words]
    else:
        words = list(keywords or [])
    include = [w for w in words if w.strip() and not w.startswith("-")]
    exclude = [w[1:] for w in words if w.startswith("-") and w[1:].strip()]
    return include, exclude


_IDENTIFIER_RE = re.compile(r"^[a-zA-Z_]\w*$")


def _kv_sort_join(meta_key: str, conn: sqlite3.Connection | None = None):
    if not _IDENTIFIER_RE.fullmatch(meta_key):
        raise ValueError(f"Invalid META_KEY: {meta_key!r}")
    if conn is not None and not conn.execute('SELECT 1 FROM tags WHERE "key" = ? LIMIT 1', (meta_key,)).fetchone():
        join = ' LEFT JOIN meta_info AS _mi ON _mi.path = m.path AND _mi."key" = ?'
        select = f", _mi.value AS {meta_key}, _mi.value_num AS {meta_key}_num"
        return join, select, "_mi.value_num", [meta_key]
    join = (
        ' LEFT JOIN meta_info AS _mi ON _mi.path = m.path AND _mi."key" = ?'
        " LEFT JOIN ("
        "SELECT i.path, t.value, t.value_num"
        " FROM tags t JOIN sources s ON s.file_hash = t.file_hash"
        " JOIN files i ON i.source = s.source"
        ' WHERE t."key" = ?'
        ") AS _tg ON _tg.path = m.path"
    )
    select = f", COALESCE(_tg.value, _mi.value) AS {meta_key}, COALESCE(_tg.value_num, _mi.value_num) AS {meta_key}_num"
    order_expr = "COALESCE(_tg.value_num, _mi.value_num)"
    return join, select, order_expr, [meta_key, meta_key]


class FileSearchEngine:
    def __init__(self, db_path):
        self.db_path = str(db_path)
        self._local = threading.local()
        self._connections = []
        self._lock = threading.Lock()

    @property
    def conn(self):
        return getattr(self._local, "conn", None)

    @conn.setter
    def conn(self, value):
        self._local.conn = value
        if value is not None:
            with self._lock:
                self._connections.append(value)

    @profiler.profile
    def _connect_if_needed(self):
        if self.conn:
            return True
        try:
            if not os.path.exists(self.db_path):
                return False
            conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            required = ("meta_info", "tags", "files", "files_full")
            for name in required:
                cur.execute("SELECT name FROM sqlite_master WHERE name=?", (name,))
                if not cur.fetchone():
                    AppLogger.warning(f"Required table/view '{name}' not found in DB.")
                    conn.close()
                    return False
            apply_read_pragmas(conn)
            self.conn = conn
            return True
        except sqlite3.OperationalError as e:
            AppLogger.warning(f"DB connection failed: {e}", exc=e)
            return False

    def close(self):
        with self._lock:
            conns, self._connections = self._connections, []
        for conn in conns:
            try:
                conn.close()
            except sqlite3.Error as e:
                AppLogger.warning(f"FileSearchEngine close failed: {e}", exc=e)
        self._local = threading.local()

    def _normalize_path(self, path):
        if is_virtual_path(path):
            parts = split_virtual_path(path)
            if parts:
                return build_virtual_path(normalize_path(parts[0]), parts[1])
        return normalize_path(path)

    @profiler.profile
    def fetch(self, sql, params):
        cur = self.conn.cursor()
        return cur.execute(sql, params).fetchall()

    @profiler.profile
    def get_kv_keys_by_prefix(self, scope: str, key_prefix: str, paths: list[str] | None = None) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        if not key_prefix or not self._connect_if_needed():
            return result
        if scope not in (SCOPE_TAG, SCOPE_META_INFO, SCOPE_ALL):
            return result
        cur = self.conn.cursor()
        like_pattern = f"{key_prefix}%"

        def _consume(rows):
            for row in rows:
                key = row["key"]
                suffix = key[len(key_prefix) :] if key else ""
                if not suffix:
                    continue
                values = result.setdefault(row["path"], [])
                if suffix not in values:
                    values.append(suffix)

        norm_paths = [self._normalize_path(p) for p in paths] if paths is not None else None
        for data_scope in iter_data_scopes(scope):
            base_sql, path_expr = key_prefix_lookup_sql(data_scope)
            if norm_paths is None:
                _consume(cur.execute(base_sql, (like_pattern,)).fetchall())
                continue
            for start in range(0, len(norm_paths), 900):
                chunk = norm_paths[start : start + 900]
                placeholders = ",".join("?" * len(chunk))
                _consume(cur.execute(f"{base_sql} AND {path_expr} IN ({placeholders})", (like_pattern, *chunk)).fetchall())
        for path, suffixes in result.items():
            result[path] = sorted(suffixes, key=lambda x: (len(x), x))
        return result

    @profiler.profile
    def get_file_record(self, path):
        if not self._connect_if_needed():
            return {}
        cur = self.conn.cursor()
        norm_path = self._normalize_path(path)
        row = cur.execute("SELECT * FROM files WHERE path = ?", (norm_path,)).fetchone()
        return dict(row) if row else {}

    @profiler.profile
    def has_source_children(self, source: str) -> bool:
        if not self._connect_if_needed():
            return False
        cur = self.conn.cursor()
        norm_source = self._normalize_path(source)
        prefix = f"{norm_source}{VIRTUAL_PATH_SEPARATOR}"
        row = cur.execute(
            """
            SELECT 1
            FROM files
            WHERE source = ?
              AND path LIKE ? ESCAPE '\\'
            LIMIT 1
            """,
            (norm_source, f"{escape_like(prefix)}%"),
        ).fetchone()
        return row is not None

    def get_all_metadata_with_locks(self, path):
        if not self._connect_if_needed():
            return {}, {}, None, {}, {}
        cur = self.conn.cursor()
        norm_path = self._normalize_path(path)
        file_row = cur.execute(
            """
            SELECT i.path, i.name, i.source, i.aspect_ratio, i.source_extension,
                   s.file_hash, s.size, s.modified, s.created, s.collected
            FROM files AS i
            JOIN sources AS s ON s.source = i.source
            WHERE i.path = ?
            """,
            (norm_path,),
        ).fetchone()
        if not file_row:
            return {}, {}, None, {}, {}
        file_record = {
            "path": file_row["path"],
            "name": file_row["name"],
            "source": file_row["source"],
            "aspect_ratio": file_row["aspect_ratio"],
            "source_extension": file_row["source_extension"],
        }
        source_record = {
            "source": file_row["source"],
            "file_hash": file_row["file_hash"],
            "size": file_row["size"],
            "modified": file_row["modified"],
            "created": file_row["created"],
            "collected": file_row["collected"],
        }
        meta_rows = cur.execute("SELECT key, value, locked FROM meta_info WHERE path = ?", (norm_path,)).fetchall()
        meta_info = {r["key"]: (r["value"], bool(r["locked"])) for r in meta_rows}
        file_hash = file_row["file_hash"]
        if not file_hash:
            return source_record, file_record, None, {}, meta_info
        tag_rows = cur.execute("SELECT key, value, locked FROM tags WHERE file_hash = ?", (file_hash,)).fetchall()
        tags_with_lock = {r["key"]: (r["value"], bool(r["locked"])) for r in tag_rows}
        return source_record, file_record, file_hash, tags_with_lock, meta_info

    @profiler.profile
    def get_collection_status(self, path):
        if not self._connect_if_needed():
            return []
        cur = self.conn.cursor()
        norm_path = self._normalize_path(path)
        rows = cur.execute(
            """SELECT cs.collector, cs.status, cs.collected_at, s.modified
            FROM files f
            JOIN collection_status cs ON cs.source = f.source
            JOIN sources s ON s.source = f.source
            WHERE f.path = ?
              AND cs.status IN ('ok', 'fail')""",
            (norm_path,),
        ).fetchall()
        result = []
        for r in rows:
            status = r["status"]
            if status == "ok" and (r["collected_at"] is None or r["modified"] is None or r["collected_at"] < r["modified"]):
                continue
            result.append((r["collector"], status))
        return result
