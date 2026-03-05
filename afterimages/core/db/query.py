from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from random import shuffle
from typing import Sequence

from .db_utils import apply_read_pragmas
from afterimages.utils.paths import normalize_path
from afterimages.utils.profiling import profiler
from afterimages.utils.logs import AppLogger


@dataclass(frozen=True)
class SearchQuery:
    keys: tuple[str, ...] | str | None = None
    keywords: tuple[str, ...] | str | None = None
    query_mode: str = 'LIKE'
    directories: tuple[str, ...] | None = None
    keyword_mode: str = 'OR'
    sort_by: str = 'name'
    ascending: bool = True
    append_mode: str = 'OR'
    keyword_separator: str | None = None
    include_subfolders: bool = True
    require_keys: bool = True

    def __post_init__(self):
        if isinstance(self.keys, list):
            object.__setattr__(self, 'keys', tuple(self.keys))
        if isinstance(self.keywords, list):
            object.__setattr__(self, 'keywords', tuple(self.keywords))
        if isinstance(self.directories, list):
            object.__setattr__(self, 'directories', tuple(self.directories))

    @profiler.profile
    def normalize_inputs(self):
        keys = [self.keys] if isinstance(self.keys, str) else list(self.keys or [])
        keywords = self.keywords
        if isinstance(keywords, str):
            keywords = [w.strip() for w in keywords.split(self.keyword_separator)] if self.keyword_separator else [keywords]
        include = [kw for kw in (keywords or []) if kw and not kw.startswith('-')]
        exclude = [kw[1:] for kw in (keywords or []) if kw and kw.startswith('-') and len(kw) > 1]
        return keys, include, exclude

    def _match_clause(self, field, keywords, op):
        if not keywords:
            return "", []
        if self.query_mode.upper() == "GLOB":
            clauses = [f"{field} GLOB ?" for _ in keywords]
            values = [f"*{kw}*" for kw in keywords]
        else:
            def esc(s):
                return s.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            clauses = [f"{field} LIKE ? ESCAPE '\\'" for _ in keywords]
            values = [f"%{esc(kw)}%" for kw in keywords]
        return f" {op} ".join(clauses), values

    def _dir_clause(self, path_field, normalize_path_func):
        if not self.directories:
            return "", []
        clauses, params = [], []
        for d in self.directories:
            if not isinstance(d, str) or not d:
                continue
            nd = normalize_path_func(str(Path(d).resolve()))
            prefix = (nd + "/") if nd else ""
            esc_p = prefix.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            if not self.include_subfolders:
                clauses.append(f"({path_field} LIKE ? ESCAPE '\\' AND {path_field} NOT LIKE ? ESCAPE '\\')")
                params.extend([f"{esc_p}%", f"{esc_p}%/%"])
            else:
                clauses.append(f"{path_field} LIKE ? ESCAPE '\\'")
                params.append(f"{esc_p}%")
        if not clauses:
            return "", []
        return "(" + " OR ".join(clauses) + ")", params

    def _kv_part(self, from_clause, key_col, val_col, path_col, select_expr,
                 other_keys, include_kw, normalize_fn):
        conds, params = [], []
        if other_keys:
            conds.append(f"{key_col} IN ({','.join('?' for _ in other_keys)})")
            params.extend(other_keys)
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

    def _build_exclude(self, has_filepath, other_keys, query_all, exclude_kw):
        parts, params = [], []
        if has_filepath or query_all:
            c, v = self._match_clause('efi.path', exclude_kw, "OR")
            parts.append(f"SELECT efi.path FROM files AS efi WHERE {c}")
            params.extend(v)
        if other_keys or query_all:
            conds, p = [], []
            if other_keys:
                conds.append(f"em.\"key\" IN ({','.join('?' for _ in other_keys)})")
                p.extend(other_keys)
            c, v = self._match_clause('em."value"', exclude_kw, "OR")
            conds.append(f"({c})")
            p.extend(v)
            parts.append(f"SELECT em.path FROM meta_info AS em WHERE {' AND '.join(conds)}")
            params.extend(p)
            conds2, p2 = [], []
            if other_keys:
                conds2.append(f"et.\"key\" IN ({','.join('?' for _ in other_keys)})")
                p2.extend(other_keys)
            c2, v2 = self._match_clause('et."value"', exclude_kw, "OR")
            conds2.append(f"({c2})")
            p2.extend(v2)
            parts.append(
                f"SELECT ei.path FROM tags AS et "
                f"JOIN sources AS es ON es.file_hash = et.file_hash "
                f"JOIN files AS ei ON ei.source = es.source "
                f"WHERE {' AND '.join(conds2)}"
            )
            params.extend(p2)
        if not parts:
            return "", []
        return " UNION ".join(parts), params

    @profiler.profile
    def _make_subquery(self, normalize_path_func, *, require_keys_override=None):
        rk = self.require_keys if require_keys_override is None else require_keys_override
        keys, include_kw, exclude_kw = self.normalize_inputs()
        if rk and not keys:
            return (None, [])
        has_filepath = '__filepath__' in keys if keys else False
        other_keys = [k for k in keys if k != '__filepath__'] if keys else []
        query_all = not keys
        parts, all_params = [], []

        if has_filepath or query_all:
            conds, params = [], []
            if include_kw:
                c, v = self._match_clause('i.path', include_kw, self.keyword_mode)
                conds.append(f"({c})")
                params.extend(v)
            dc, dp = self._dir_clause('i.path', normalize_path_func)
            if dc:
                conds.append(dc)
                params.extend(dp)
            w = f"WHERE {' AND '.join(conds)}" if conds else ""
            parts.append(
                f"SELECT i.path, '__filepath__' AS \"key\", i.path AS \"value\" "
                f"FROM files AS i {w}"
            )
            all_params.extend(params)

        if other_keys or query_all:
            sql, p = self._kv_part(
                'meta_info AS mi', 'mi."key"', 'mi."value"', 'mi.path',
                'mi.path, mi."key", mi."value"',
                other_keys, include_kw, normalize_path_func,
            )
            parts.append(sql)
            all_params.extend(p)

            sql, p = self._kv_part(
                'tags AS t '
                'JOIN sources AS s ON s.file_hash = t.file_hash '
                'JOIN files AS i ON i.source = s.source',
                't."key"', 't."value"', 'i.path',
                'i.path, t."key", t."value"',
                other_keys, include_kw, normalize_path_func,
            )
            parts.append(sql)
            all_params.extend(p)

        if not parts:
            return (None, [])
        subquery = " UNION ALL ".join(parts)
        if exclude_kw:
            exc_sql, exc_params = self._build_exclude(
                has_filepath, other_keys, query_all, exclude_kw
            )
            if exc_sql:
                subquery = (
                    f"SELECT sq.path, sq.\"key\", sq.\"value\" "
                    f"FROM ({subquery}) AS sq "
                    f"WHERE sq.path NOT IN ({exc_sql})"
                )
                all_params.extend(exc_params)
        return (subquery, all_params)


_SORT_COLUMNS = {
    'path': 'path', 'name': 'name', 'created': 'created',
    'modified': 'modified', 'size': 'size', 'collected': 'collected',
}


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
            conn = sqlite3.connect(f'file:{self.db_path}?mode=ro', uri=True, check_same_thread=True)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            required = ('meta_info', 'tags', 'files', 'files_full')
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
            AppLogger.warning(f'DB connection failed: {e}', exc=e)
            return False

    def _normalize_path(self, path):
        return normalize_path(path)

    @staticmethod
    def _build_order_clause(sort_by, ascending):
        col = _SORT_COLUMNS.get(sort_by)
        if not col:
            return ""
        order = 'ASC' if ascending else 'DESC'
        return f' ORDER BY m."{col}" {order}'

    @profiler.profile
    def _build_path_query(self, queries):
        parts, modes, params = [], [], []
        for q in queries:
            subq, p = q._make_subquery(self._normalize_path)
            if not subq:
                if q.append_mode == 'AND':
                    return None, []
                continue
            parts.append(f"SELECT DISTINCT path FROM ({subq}) s0")
            modes.append(q.append_mode)
            params.extend(p)
        if not parts:
            return None, []
        combined = parts[0]
        for i in range(1, len(parts)):
            op = "INTERSECT" if modes[i] == 'AND' else "UNION"
            combined = f"{combined} {op} {parts[i]}"
        return combined, params

    @profiler.profile
    def _fetch_sorted(self, columns, path_query, params, sort_by, ascending):
        cur = self.conn.cursor()
        col_str = ', '.join(f'm.{c}' for c in columns)
        order = self._build_order_clause(sort_by, ascending)
        sql = f"SELECT {col_str} FROM files_full AS m JOIN ({path_query}) AS s USING(path){order}"
        rows = cur.execute(sql, params).fetchall()
        if sort_by == 'random':
            rows = list(rows)
            shuffle(rows)
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
            ['path', 'source', 'aspect_ratio'],
            path_query, params, query.sort_by, query.ascending,
        )
        return (
            [r['path'] for r in rows],
            [r['source'] for r in rows],
            [r['aspect_ratio'] or 1.0 for r in rows],
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
            ['path', 'aspect_ratio'],
            path_query, params, last.sort_by, last.ascending,
        )
        return ([r['path'] for r in rows], [r['aspect_ratio'] or 1.0 for r in rows])

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
        return [(row['key'], row['freq']) for row in rows]

    @profiler.profile
    def _explain_query_plan(self, sql, params):
        try:
            cur = self.conn.cursor()
            rows = cur.execute(f'EXPLAIN QUERY PLAN {sql}', params).fetchall()
            plan_lines = [f"[{row['id']}] {row['detail']}" for row in rows]
            AppLogger.info('========= SQLite Execution Plan =========')
            for line in plan_lines:
                AppLogger.info(line)
        except Exception as e:
            AppLogger.warning(f'EXPLAIN QUERY PLAN failed: {e}')
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
    def get_tags_by_path(self, path):
        if not self._connect_if_needed():
            return {}
        cur = self.conn.cursor()
        norm_path = self._normalize_path(path)
        row = cur.execute(
            """
            SELECT s.file_hash
            FROM files AS i
            JOIN sources AS s ON s.source = i.source
            WHERE i.path = ?
            """,
            (norm_path,)
        ).fetchone()
        if not row:
            return {}
        fid = row["file_hash"]
        rows = cur.execute(
            "SELECT key, value FROM tags WHERE file_hash = ?",
            (fid,)
        ).fetchall()
        return {r["key"]: r["value"] for r in rows}

    @profiler.profile
    def get_file_record(self, path):
        if not self._connect_if_needed():
            return {}
        cur = self.conn.cursor()
        norm_path = self._normalize_path(path)
        row = cur.execute(
            "SELECT * FROM files WHERE path = ?",
            (norm_path,)
        ).fetchone()
        return dict(row) if row else {}

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
            (norm_path,)
        ).fetchone()
        return dict(row) if row else {}

    def get_all_metadata(self, path):
        return [self.get_source_by_path(path), self.get_file_record(path), self.get_tags_by_path(path), self.get_meta_info_by_path(path)]