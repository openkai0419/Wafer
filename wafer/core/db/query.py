from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from ...constants import VIRTUAL_PATH_SEPARATOR
from .db_utils import apply_read_pragmas, build_like_condition, escape_like
from .key_value import SCOPE_ALL, SCOPE_META_INFO, SCOPE_TAG, iter_data_scopes, key_prefix_lookup_sql
from ...utils.paths import normalize_path
from ...utils.virtual_paths import build_virtual_path, is_virtual_path, split_virtual_path
from ...utils.profiling import profiler
from ...utils.logs import AppLogger


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


def standard_key_columns_with_num(key: str) -> tuple[str, str, str, str] | None:
    cols = standard_key_columns(key)
    if cols is None:
        return None
    from_clause, path_col, val_col = cols
    if key in STANDARD_KEYS_SOURCES:
        return from_clause, path_col, val_col, f"s.{key}"
    return from_clause, path_col, val_col, "NULL"


@dataclass(frozen=True)
class SearchQuery:
    keys: tuple[str, ...] | str | None = None
    keywords: tuple[str, ...] | str | None = None
    query_mode: str = "LIKE"
    directories: tuple[str, ...] | None = None
    keyword_mode: str = "OR"
    sort_by: str = "name"
    ascending: bool = True
    append_mode: str = "OR"
    keyword_separator: str | None = None
    include_subfolders: bool = True
    require_keys: bool = True

    def __post_init__(self):
        if isinstance(self.keys, list):
            object.__setattr__(self, "keys", tuple(self.keys))
        if isinstance(self.keywords, list):
            object.__setattr__(self, "keywords", tuple(self.keywords))
        if isinstance(self.directories, list):
            object.__setattr__(self, "directories", tuple(self.directories))

    @profiler.profile
    def normalize_inputs(self):
        keys = [self.keys] if isinstance(self.keys, str) else list(self.keys or [])
        keywords = self.keywords
        if isinstance(keywords, str):
            keywords = [w.strip() for w in keywords.split(self.keyword_separator)] if self.keyword_separator else [keywords]
        include = [kw for kw in (keywords or []) if kw and not kw.startswith("-")]
        exclude = [kw[1:] for kw in (keywords or []) if kw and kw.startswith("-") and len(kw) > 1]
        return keys, include, exclude

    def _match_clause(self, field, keywords, op):
        return build_like_condition(field, keywords, op, self.query_mode)

    def _dir_clause(self, path_field, normalize_path_func):
        if not self.directories:
            return "", []
        clauses, params = [], []
        for d in self.directories:
            if not isinstance(d, str) or not d:
                continue
            nd = normalize_path_func(str(Path(d).resolve()))
            prefix = (nd + "/") if nd else ""
            esc_p = escape_like(prefix)
            if not self.include_subfolders:
                clauses.append(f"({path_field} LIKE ? ESCAPE '\\' AND {path_field} NOT LIKE ? ESCAPE '\\')")
                params.extend([f"{esc_p}%", f"{esc_p}%/%"])
            else:
                clauses.append(f"{path_field} LIKE ? ESCAPE '\\'")
                params.append(f"{esc_p}%")
        if not clauses:
            return "", []
        return "(" + " OR ".join(clauses) + ")", params

    def _kv_part(self, from_clause, key_col, val_col, path_col, select_expr, other_keys, include_kw, normalize_fn, exclude_keys=()):
        conds, params = [], []
        if other_keys:
            conds.append(f"{key_col} IN ({','.join('?' for _ in other_keys)})")
            params.extend(other_keys)
        if exclude_keys:
            conds.append(f"{key_col} NOT IN ({','.join('?' for _ in exclude_keys)})")
            params.extend(exclude_keys)
        if include_kw:
            c, v = self._match_clause(val_col, include_kw, self.keyword_mode)
            conds.append(f"({c})")
            params.extend(v)
        dc, dp = self._dir_clause(path_col, normalize_fn)
        if dc:
            conds.append(dc)
            params.extend(dp)
        w = f"WHERE {' AND '.join(conds)}" if conds else ""
        return f"SELECT {select_expr} FROM {from_clause} {w}", params

    def _file_hash_part(self, include_kw, normalize_fn):
        conds, params = [], []
        if include_kw:
            c, v = self._match_clause("s.file_hash", include_kw, self.keyword_mode)
            conds.append(f"({c})")
            params.extend(v)
        dc, dp = self._dir_clause("i.path", normalize_fn)
        if dc:
            conds.append(dc)
            params.extend(dp)
        w = f"WHERE {' AND '.join(conds)}" if conds else ""
        return f'SELECT i.path, \'{SYSTEM_FILE_HASH_KEY}\' AS "key", s.file_hash AS "value" FROM sources AS s JOIN files AS i ON i.source = s.source {w}', params

    def _build_exclude(self, keys, query_all, exclude_kw):
        parts, params = [], []
        kv_keys = [k for k in keys if k != SYSTEM_FILE_HASH_KEY]
        std_keys = [k for k in kv_keys if k in STANDARD_KEYS] if not query_all else list(STANDARD_KEYS)
        non_std_keys = [k for k in kv_keys if k not in STANDARD_KEYS]
        if query_all or non_std_keys:
            conds, p = [], []
            if non_std_keys:
                conds.append(f'em."key" IN ({",".join("?" for _ in non_std_keys)})')
                p.extend(non_std_keys)
            elif query_all:
                conds.append('em."key" <> ?')
                p.append(SYSTEM_FILE_HASH_KEY)
            c, v = self._match_clause('em."value"', exclude_kw, "OR")
            conds.append(f"({c})")
            p.extend(v)
            parts.append(f"SELECT em.path FROM meta_info AS em WHERE {' AND '.join(conds)}")
            params.extend(p)

            conds2, p2 = [], []
            if non_std_keys:
                conds2.append(f'et."key" IN ({",".join("?" for _ in non_std_keys)})')
                p2.extend(non_std_keys)
            c2, v2 = self._match_clause('et."value"', exclude_kw, "OR")
            conds2.append(f"({c2})")
            p2.extend(v2)
            parts.append(f"SELECT ei.path FROM tags AS et JOIN sources AS es ON es.file_hash = et.file_hash JOIN files AS ei ON ei.source = es.source WHERE {' AND '.join(conds2)}")
            params.extend(p2)

        for k in std_keys:
            cols = standard_key_columns(k)
            if cols is None:
                continue
            from_clause, path_col, val_col = cols
            c, v = self._match_clause(val_col, exclude_kw, "OR")
            parts.append(f"SELECT {path_col} AS path FROM {from_clause} WHERE ({c})")
            params.extend(v)

        if query_all or SYSTEM_FILE_HASH_KEY in keys:
            c3, p3 = self._match_clause("es.file_hash", exclude_kw, "OR")
            parts.append(f"SELECT ei.path FROM sources AS es JOIN files AS ei ON ei.source = es.source WHERE ({c3})")
            params.extend(p3)
        if not parts:
            return "", []
        return " UNION ".join(parts), params

    @profiler.profile
    def _make_subquery(self, normalize_path_func, *, require_keys_override=None):
        rk = self.require_keys if require_keys_override is None else require_keys_override
        keys, include_kw, exclude_kw = self.normalize_inputs()
        if rk and not keys:
            return (None, [])
        query_all = not keys
        kv_keys = [k for k in keys if k != SYSTEM_FILE_HASH_KEY]
        non_std_keys = [k for k in kv_keys if k not in STANDARD_KEYS]
        std_keys = [k for k in kv_keys if k in STANDARD_KEYS] if not query_all else list(STANDARD_KEYS)
        parts, all_params = [], []

        if query_all or non_std_keys:
            sql, p = self._kv_part(
                "meta_info AS mi",
                'mi."key"',
                'mi."value"',
                "mi.path",
                'mi.path, mi."key", mi."value"',
                non_std_keys if not query_all else [],
                include_kw,
                normalize_path_func,
                (SYSTEM_FILE_HASH_KEY,) if query_all else (),
            )
            parts.append(sql)
            all_params.extend(p)

            sql, p = self._kv_part(
                "tags AS t JOIN sources AS s ON s.file_hash = t.file_hash JOIN files AS i ON i.source = s.source",
                't."key"',
                't."value"',
                "i.path",
                'i.path, t."key", t."value"',
                non_std_keys if not query_all else [],
                include_kw,
                normalize_path_func,
            )
            parts.append(sql)
            all_params.extend(p)

        for k in std_keys:
            sql, p = self._standard_kv_part(k, include_kw, normalize_path_func)
            parts.append(sql)
            all_params.extend(p)

        if query_all or SYSTEM_FILE_HASH_KEY in keys:
            sql, p = self._file_hash_part(include_kw, normalize_path_func)
            parts.append(sql)
            all_params.extend(p)

        if not parts:
            return (None, [])
        subquery = " UNION ALL ".join(parts)
        if exclude_kw:
            exc_sql, exc_params = self._build_exclude(keys if not query_all else [], query_all, exclude_kw)
            if exc_sql:
                subquery = f'SELECT sq.path, sq."key", sq."value" FROM ({subquery}) AS sq WHERE sq.path NOT IN ({exc_sql})'
                all_params.extend(exc_params)
        return (subquery, all_params)

    def _standard_kv_part(self, key: str, include_kw, normalize_fn):
        cols = standard_key_columns(key)
        if cols is None:
            return 'SELECT NULL AS path, NULL AS "key", NULL AS "value" WHERE 0', []
        from_clause, path_col, val_col = cols
        conds, params = [], []
        if include_kw:
            c, v = self._match_clause(val_col, include_kw, self.keyword_mode)
            conds.append(f"({c})")
            params.extend(v)
        dc, dp = self._dir_clause(path_col, normalize_fn)
        if dc:
            conds.append(dc)
            params.extend(dp)
        w = f"WHERE {' AND '.join(conds)}" if conds else ""
        return f'SELECT {path_col} AS path, \'{key}\' AS "key", {val_col} AS "value" FROM {from_clause} {w}', params


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
        self.conn = None

    @profiler.profile
    def _connect_if_needed(self):
        if self.conn:
            return True
        try:
            if not os.path.exists(self.db_path):
                return False
            conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, check_same_thread=True)
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
        if self.conn is not None:
            try:
                self.conn.close()
            except sqlite3.Error as e:
                AppLogger.warning(f"FileSearchEngine close failed: {e}", exc=e)
            self.conn = None

    def _normalize_path(self, path):
        if is_virtual_path(path):
            parts = split_virtual_path(path)
            if parts:
                return build_virtual_path(normalize_path(parts[0]), parts[1])
        return normalize_path(path)

    @profiler.profile
    def _build_path_query(self, queries):
        parts, modes, params = [], [], []
        for q in queries:
            subq, p = q._make_subquery(self._normalize_path)
            if not subq:
                if q.append_mode == "AND":
                    return None, []
                continue
            parts.append(f"SELECT DISTINCT path FROM ({subq}) s0")
            modes.append(q.append_mode)
            params.extend(p)
        if not parts:
            return None, []
        combined = parts[0]
        for i in range(1, len(parts)):
            op = "INTERSECT" if modes[i] == "AND" else "UNION"
            combined = f"{combined} {op} {parts[i]}"
        return combined, params

    @profiler.profile
    def _fetch_sorted(self, columns, path_query, params, sort_by, ascending):
        from ...plugin.query.handler import sort_registry

        cur = self.conn.cursor()
        plugin = sort_registry.get(sort_by)
        sort_column = getattr(plugin, "SORT_COLUMN", None) if plugin else None
        meta_key = getattr(plugin, "META_KEY", None) if plugin else None
        has_custom_sort = plugin and "sort_rows" in vars(plugin)
        cols = list(columns)
        if sort_column and sort_column not in cols:
            cols.append(sort_column)
        col_str = ", ".join(f"m.{c}" for c in cols)
        if sort_column:
            if has_custom_sort:
                sql = f"SELECT {col_str} FROM files_full AS m JOIN ({path_query}) AS s USING(path)"
                rows = list(cur.execute(sql, params).fetchall())
                return plugin.sort_rows(rows, ascending)
            order = "ASC" if ascending else "DESC"
            sql = f"SELECT {col_str} FROM files_full AS m JOIN ({path_query}) AS s USING(path) ORDER BY m.{sort_column} {order}"
            return cur.execute(sql, params).fetchall()
        if has_custom_sort:
            if meta_key:
                kv_join, kv_select, _, kv_params = _kv_sort_join(meta_key, self.conn)
                sql = f"SELECT {col_str}{kv_select} FROM files_full AS m JOIN ({path_query}) AS s USING(path){kv_join}"
                rows = list(cur.execute(sql, [*params, *kv_params]).fetchall())
            else:
                sql = f"SELECT {col_str} FROM files_full AS m JOIN ({path_query}) AS s USING(path)"
                rows = list(cur.execute(sql, params).fetchall())
            rows = plugin.sort_rows(rows, ascending)
        elif meta_key:
            order = "ASC" if ascending else "DESC"
            kv_join, _, kv_order, kv_params = _kv_sort_join(meta_key, self.conn)
            join_clause = f"{kv_join} ORDER BY {kv_order} {order}"
            sql = f"SELECT {col_str} FROM files_full AS m JOIN ({path_query}) AS s USING(path){join_clause}"
            rows = cur.execute(sql, [*params, *kv_params]).fetchall()
        else:
            sql = f"SELECT {col_str} FROM files_full AS m JOIN ({path_query}) AS s USING(path)"
            rows = cur.execute(sql, params).fetchall()
        return rows

    @profiler.profile
    def fetch(self, sql, params):
        cur = self.conn.cursor()
        return cur.execute(sql, params).fetchall()

    @profiler.profile
    def search(self, query):
        if not self._connect_if_needed():
            return ([], [], [])
        path_query, params = self._build_path_query([query])
        if not path_query:
            return ([], [], [])
        rows = self._fetch_sorted(
            ["path", "source", "aspect_ratio"],
            path_query,
            params,
            query.sort_by,
            query.ascending,
        )
        return (
            [r["path"] for r in rows],
            [r["source"] for r in rows],
            [r["aspect_ratio"] or 1.0 for r in rows],
        )

    @profiler.profile
    def search_multi(self, queries):
        if not self._connect_if_needed():
            return ([], [])
        path_query, params = self._build_path_query(queries)
        if not path_query:
            return ([], [])
        last = queries[-1]
        rows = self._fetch_sorted(
            ["path", "aspect_ratio"],
            path_query,
            params,
            last.sort_by,
            last.ascending,
        )
        return ([r["path"] for r in rows], [r["aspect_ratio"] or 1.0 for r in rows])

    @profiler.profile
    def list_all_keys(self, query, sort_by_freq=False):
        if not self._connect_if_needed():
            return []
        cur = self.conn.cursor()
        q, p = query._make_subquery(self._normalize_path, require_keys_override=False)
        if not q:
            return []
        order = "ORDER BY freq DESC" if sort_by_freq else "ORDER BY key"
        sql = f"""
            SELECT key, COUNT(*) AS freq
            FROM (
                SELECT DISTINCT path, key FROM ({q}) AS raw
            ) AS items
            GROUP BY key
            {order}
        """
        rows = cur.execute(sql, p).fetchall()
        return [(row["key"], row["freq"]) for row in rows]

    @profiler.profile
    def sample_values(self, key: str, limit: int = 10) -> list[str]:
        if not self._connect_if_needed():
            return []
        cur = self.conn.cursor()
        if key == SYSTEM_FILE_HASH_KEY:
            rows = cur.execute(
                "SELECT DISTINCT file_hash AS value FROM sources ORDER BY file_hash LIMIT ?",
                (limit,),
            ).fetchall()
            return [row["value"] for row in rows]
        if key in STANDARD_KEYS_FILES:
            rows = cur.execute(
                f"SELECT DISTINCT {key} AS value FROM files WHERE {key} IS NOT NULL LIMIT ?",
                (limit,),
            ).fetchall()
            return [row["value"] for row in rows]
        if key in STANDARD_KEYS_SOURCES:
            rows = cur.execute(
                f"SELECT DISTINCT CAST({key} AS TEXT) AS value FROM sources WHERE {key} IS NOT NULL LIMIT ?",
                (limit,),
            ).fetchall()
            return [row["value"] for row in rows]
        rows = cur.execute(
            "SELECT DISTINCT value FROM meta_info WHERE key = ? LIMIT ?",
            (key, limit),
        ).fetchall()
        return [row["value"] for row in rows]

    @profiler.profile
    def _explain_query_plan(self, sql, params):
        try:
            cur = self.conn.cursor()
            rows = cur.execute(f"EXPLAIN QUERY PLAN {sql}", params).fetchall()
            plan_lines = [f"[{row['id']}] {row['detail']}" for row in rows]
            AppLogger.info("========= SQLite Execution Plan =========")
            for line in plan_lines:
                AppLogger.info(line)
        except Exception as e:
            AppLogger.warning(f"EXPLAIN QUERY PLAN failed: {e}")
            return None

    @profiler.profile
    def get_meta_info_by_path(self, path):
        if not self._connect_if_needed():
            return {}
        cur = self.conn.cursor()
        norm_path = self._normalize_path(path)
        row = cur.execute("SELECT path FROM files WHERE path = ?", (norm_path,)).fetchone()
        if not row:
            return {}
        fid = row["path"]
        rows = cur.execute("SELECT key, value FROM meta_info WHERE path = ?", (fid,)).fetchall()
        return {r["key"]: r["value"] for r in rows}

    @profiler.profile
    def get_meta_info_with_lock_by_path(self, path):
        if not self._connect_if_needed():
            return {}
        cur = self.conn.cursor()
        norm_path = self._normalize_path(path)
        row = cur.execute("SELECT path FROM files WHERE path = ?", (norm_path,)).fetchone()
        if not row:
            return {}
        rows = cur.execute("SELECT key, value, locked FROM meta_info WHERE path = ?", (row["path"],)).fetchall()
        return {r["key"]: (r["value"], bool(r["locked"])) for r in rows}

    @profiler.profile
    def get_tags_with_lock_by_path(self, path):
        if not self._connect_if_needed():
            return None, {}
        cur = self.conn.cursor()
        norm_path = self._normalize_path(path)
        row = cur.execute(
            """
            SELECT s.file_hash
            FROM files AS i
            JOIN sources AS s ON s.source = i.source
            WHERE i.path = ?
            """,
            (norm_path,),
        ).fetchone()
        if not row:
            return None, {}
        fid = row["file_hash"]
        rows = cur.execute("SELECT key, value, locked FROM tags WHERE file_hash = ?", (fid,)).fetchall()
        return fid, {r["key"]: (r["value"], bool(r["locked"])) for r in rows}

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
    def get_tag_keys_by_prefix(self, key_prefix: str, paths: list[str] | None = None) -> dict[str, list[str]]:
        return self.get_kv_keys_by_prefix("tag", key_prefix, paths)

    @profiler.profile
    def get_meta_keys_by_prefix(self, key_prefix: str, paths: list[str] | None = None) -> dict[str, list[str]]:
        return self.get_kv_keys_by_prefix("meta_info", key_prefix, paths)

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

    @profiler.profile
    def get_source_by_path(self, path: str) -> dict:
        if not self._connect_if_needed():
            return {}
        cur = self.conn.cursor()
        norm_path = self._normalize_path(path)
        row = cur.execute(
            """
            SELECT s.*
            FROM files AS i
            JOIN sources AS s ON s.source = i.source
            WHERE i.path = ?
            """,
            (norm_path,),
        ).fetchone()
        return dict(row) if row else {}

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
