import os
import sqlite3
from pathlib import Path
from random import shuffle
from typing import Sequence
from ..common.funcs import normalize_path
from ..common.profiling import logger, profiler

class MetaQuery:
    def __init__(
        self,
        keys: Sequence[str] | str | None = None,
        keywords: Sequence[str] | str | None = None,
        query_mode: str = 'LIKE',
        directories: Sequence[str] | None = None,
        keyword_mode: str = 'OR',
        sort_by: str = 'name',
        ascending: bool = True,
        append_mode: str = 'OR',
        splittext: str | None = None,
        only_direct_children: bool = False,
        require_keys: bool = True,
    ) -> None:
        self.keys = keys
        self.keywords = keywords
        self.query_mode = query_mode
        self.directories = directories
        self.keyword_mode = keyword_mode
        self.sort_by = sort_by
        self.ascending = ascending
        self.append_mode = append_mode
        self.splittext = splittext
        self.only_direct_children = only_direct_children
        self.require_keys = require_keys

    def __eq__(self, other):
        if not isinstance(other, MetaQuery):
            return NotImplemented
        return (
            self.keys,
            self.keywords,
            self.query_mode,
            self.directories,
            self.keyword_mode,
            self.sort_by,
            self.ascending,
            self.append_mode,
            self.splittext,
            self.only_direct_children,
            self.require_keys,
        ) == (
            other.keys,
            other.keywords,
            other.query_mode,
            other.directories,
            other.keyword_mode,
            other.sort_by,
            other.ascending,
            other.append_mode,
            other.splittext,
            other.only_direct_children,
            other.require_keys,
        )

    def __hash__(self):
        return hash((tuple(self.keys or []), tuple(self.keywords or []), self.query_mode, tuple(self.directories or []), self.keyword_mode, self.sort_by, self.ascending, self.append_mode, self.splittext, self.only_direct_children, self.require_keys))

    @profiler.profile
    def normalize_inputs(self):
        keys = [self.keys] if isinstance(self.keys, str) else self.keys or []
        keywords = self.keywords
        if isinstance(keywords, str):
            keywords = [w.strip() for w in keywords.split(self.splittext)] if self.splittext else [keywords]
        include = [kw for kw in keywords or [] if not kw.startswith('-')]
        exclude = [kw[1:] for kw in keywords or [] if kw.startswith('-')]
        return (keys, include, exclude)

    @profiler.profile
    def build_conditions(self, normalize_path_func, require_keys=True):
        keys, include_keywords, exclude_keywords = self.normalize_inputs()
        if require_keys and (not keys):
            return (None, None, None)
        def escape_like(s: str) -> str:
            return s.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        conditions = []
        params = []
        if keys:
            key_placeholders = ','.join(('?' for _ in keys))
            conditions.append(f'key IN ({key_placeholders})')
            params.extend(keys)
        def match_clause(field, keywords, operator):
            if not keywords:
                return ('', [])
            mode = self.query_mode.upper()
            if mode == 'GLOB':
                clause_format = f"{field} GLOB ?"
                values = [f"*{kw}*" for kw in keywords]
                clauses = [clause_format for _ in keywords]
                return (' ' + operator + ' ').join(clauses), values
            clause_format = f"{field} LIKE ? ESCAPE '\\'"
            values = [f"%{escape_like(kw)}%" for kw in keywords]
            clauses = [clause_format for _ in keywords]
            return (' ' + operator + ' ').join(clauses), values
        if include_keywords:
            clause, values = match_clause('value', include_keywords, self.keyword_mode)
            conditions.append(f'({clause})')
            params.extend(values)
        if exclude_keywords:
            clause_ex_like, values_ex = match_clause('mi2.value', exclude_keywords, 'OR')
            if keys:
                key_placeholders = ','.join(('?' for _ in keys))
                conditions.append(f"NOT EXISTS (SELECT 1 FROM meta_info mi2 WHERE mi2.path = meta_info.path AND mi2.key IN ({key_placeholders}) AND ({clause_ex_like}))")
                params.extend(keys)
            else:
                conditions.append(f"NOT EXISTS (SELECT 1 FROM meta_info mi2 WHERE mi2.path = meta_info.path AND ({clause_ex_like}))")
            params.extend(values_ex)
        if self.directories:
            dirs = [str(Path(d).resolve()) for d in self.directories if isinstance(d, str) and d]
            dir_clauses = []
            dir_params = []
            for d in dirs:
                norm_dir = normalize_path_func(str(d))
                prefix = norm_dir + '/' if norm_dir else ''
                esc_prefix = prefix.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
                if self.only_direct_children:
                    dir_clauses.append("(path LIKE ? ESCAPE '\\' AND path NOT LIKE ? ESCAPE '\\')")
                    dir_params.extend([f'{esc_prefix}%', f'{esc_prefix}%/%'])
                else:
                    dir_clauses.append("path LIKE ? ESCAPE '\\'")
                    dir_params.append(f'{esc_prefix}%')
            if dir_clauses:
                conditions.append("(" + " OR ".join(dir_clauses) + ")")
                params.extend(dir_params)
        return (conditions, params, keys)

    @profiler.profile
    def to_sql(self, normalize_path_func):
        conditions, params, keys = self.build_conditions(normalize_path_func, require_keys=self.require_keys)
        if conditions is None:
            return (None, None)
        return (f"SELECT path, key, value FROM meta_info WHERE {' AND '.join(conditions)}", params)

    @profiler.profile
    def to_path_query(self, normalize_path_func):
        conditions, params, keys = self.build_conditions(normalize_path_func, require_keys=self.require_keys)
        if conditions is None:
            return (None, None)
        return (f"SELECT DISTINCT path FROM meta_info WHERE {' AND '.join(conditions)}", params)

class MetaInfoSearchEngine:
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
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='meta_info'")
            if not cur.fetchone():
                logger.warning("Table 'meta_info' not found in DB.")
                return False
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='meta'")
            if not cur.fetchone():
                logger.warning("Table 'meta' not found in DB.")
                return False
            self.conn = conn
            return True
        except sqlite3.OperationalError as e:
            logger.warning(f'DB connection failed: {e}')
            return False

    def _normalize_path(self, path):
        #return normalize_path(path)
        return path.replace('\\', '/').rstrip('/')

    @profiler.profile
    def _build_sort_clause(self, sort_by, ascending):
        sort_column_map = {'path': 'path', 'name': 'name', 'created': 'created', 'modified': 'mtime', 'size': 'size', 'collected': 'collected_at', 'random': None}
        if sort_by not in sort_column_map and sort_by != 'random':
            sort_by = 'path'
        sort_column = sort_column_map.get(sort_by)
        order = 'ASC' if ascending else 'DESC'
        return (sort_column, order)

    @profiler.profile
    def _fetch_paths_with_aspect_ratio(self, cur, paths, sort_by, ascending, batch_size=700):
        if not paths:
            return ([], [])
        sort_column, order = self._build_sort_clause(sort_by, ascending)
        cur.execute("CREATE TEMP TABLE IF NOT EXISTS _tmp_paths(path TEXT PRIMARY KEY) WITHOUT ROWID")
        cur.execute("DELETE FROM _tmp_paths")
        cur.executemany("INSERT INTO _tmp_paths(path) VALUES (?)", [(p,) for p in paths])
        if sort_by == 'random':
            rows = cur.execute(
                """
                SELECT m.path, m.aspect_ratio
                FROM meta AS m
                JOIN _tmp_paths t ON t.path = m.path
                """
            ).fetchall()
            rows = list(rows)
            shuffle(rows)
            return ([row['path'] for row in rows], [row['aspect_ratio'] for row in rows])
        if sort_column:
            rows = cur.execute(
                f"""
                SELECT m.path, m.aspect_ratio, m.{sort_column} AS sort_value
                FROM meta AS m
                JOIN _tmp_paths t ON t.path = m.path
                ORDER BY sort_value {order}
                """
            ).fetchall()
            return ([row['path'] for row in rows], [row['aspect_ratio'] for row in rows])
        rows = cur.execute(
            """
            SELECT m.path, m.aspect_ratio
            FROM meta AS m
            JOIN _tmp_paths t ON t.path = m.path
            """
        ).fetchall()
        return ([row['path'] for row in rows], [row['aspect_ratio'] for row in rows])



    @profiler.profile
    def search(self, query):
        if not self._connect_if_needed():
            return []
        cur = self.conn.cursor()
        sql, params = query.to_sql(self._normalize_path)
        if not sql:
            return []
        rows = cur.execute(sql, params).fetchall()
        return [(row['path'], row['key'], row['value']) for row in rows]

    @profiler.profile
    def get(self, query):
        if not self._connect_if_needed():
            return ([], [])
        cur = self.conn.cursor()
        sql, params = query.to_path_query(self._normalize_path)
        if not sql:
            return ([], [])
        try:
            rows = cur.execute(sql, params).fetchall()
        except sqlite3.DatabaseError as e:
            logger.error(f'DB query failed: {e}')
            return ([], [])
        paths = [row['path'] for row in rows]
        return self._fetch_paths_with_aspect_ratio(cur, paths, query.sort_by, query.ascending)

    @profiler.profile
    def get_combined(self, queries):
        if not self._connect_if_needed():
            return ([], [])
        cur = self.conn.cursor()
        parts = []
        params = []
        for idx, q in enumerate(queries):
            sql, p = q.to_path_query(self._normalize_path)
            if not sql:
                if q.append_mode == 'AND':
                    return ([], [])
                continue
            parts.append((f"q{len(parts)}", sql, q.append_mode))
            params.extend(p)
        if not parts:
            return ([], [])
        ctes = []
        for name, sql, _ in parts:
            ctes.append(f"{name} AS ({sql})")
        combined = f"SELECT path FROM {parts[0][0]}"
        for i in range(1, len(parts)):
            op = "INTERSECT" if parts[i][2] == 'AND' else "UNION"
            combined = f"({combined}) {op} (SELECT path FROM {parts[i][0]})"
        sort_col, order = self._build_sort_clause(queries[-1].sort_by, queries[-1].ascending)
        if sort_col:
            final_query = f"""
                WITH {', '.join(ctes)}
                SELECT m.path, m.aspect_ratio
                FROM meta m
                JOIN ({combined}) c ON c.path = m.path
                ORDER BY m.{sort_col} {order}
            """
        else:
            final_query = f"""
                WITH {', '.join(ctes)}
                SELECT m.path, m.aspect_ratio
                FROM meta m
                JOIN ({combined}) c ON c.path = m.path
            """
        rows = cur.execute(final_query, params).fetchall()
        if queries[-1].sort_by == 'random':
            rows = list(rows)
            shuffle(rows)
        return ([row['path'] for row in rows], [row['aspect_ratio'] for row in rows])

    @profiler.profile
    def list_all_keys(self, query, sort_by_freq=False, include_freq=False):
        if not self._connect_if_needed():
            return []
        cur = self.conn.cursor()
        filters, params, _ = query.build_conditions(self._normalize_path, require_keys=False)
        if filters is None:
            return []
        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ''
        group_order_clause = 'GROUP BY key ORDER BY ' + ('freq DESC' if sort_by_freq else 'key')
        query_sql = f'SELECT key, COUNT(*) as freq FROM meta_info {where_clause} {group_order_clause}'
        rows = cur.execute(query_sql, params).fetchall()
        return [(row['key'], row['freq']) if include_freq else row['key'] for row in rows]

    @profiler.profile
    def explain_query_plan(self, query):
        if not self._connect_if_needed():
            logger.warning('DB connection failed: skipping explain_query_plan')
            return None
        sql, params = query.to_sql(self._normalize_path)
        if not sql:
            logger.info('Query invalid, skipping EXPLAIN QUERY PLAN')
            return None
        explain_sql = f'EXPLAIN QUERY PLAN {sql}'
        try:
            cur = self.conn.cursor()
            rows = cur.execute(explain_sql, params).fetchall()
            plan_lines = [f"[{row['id']}] {row['detail']}" for row in rows]
            logger.info('=== SQLite Execution Plan ===')
            for line in plan_lines:
                logger.info(line)
        except Exception as e:
            logger.warning(f'EXPLAIN QUERY PLAN failed: {e}')
            return None
