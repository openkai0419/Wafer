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
            conditions.append(f'key IN ({key_placeholders})')   # ← items.key を前提
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

        # value は items.value を想定
        if include_keywords:
            clause, values = match_clause('value', include_keywords, self.keyword_mode)
            conditions.append(f'({clause})')
            params.extend(values)

        # 除外は「同じ file_hash にその語が無い」を NOT EXISTS で
        if exclude_keywords:
            clause_ex_like, values_ex = match_clause('mi2.value', exclude_keywords, 'OR')
            if keys:
                key_placeholders = ','.join(('?' for _ in keys))
                conditions.append(
                    "NOT EXISTS ("
                    "  SELECT 1"
                    "  FROM meta_info mi2"
                    "  JOIN meta m2 ON m2.file_hash = mi2.file_hash"
                    "  WHERE m2.path = items.path"
                    f"    AND mi2.key IN ({key_placeholders})"
                    f"    AND ({clause_ex_like})"
                    ")"
                )
                params.extend(keys)
            else:
                conditions.append(
                "NOT EXISTS ("
                "  SELECT 1"
                "  FROM meta_info mi2"
                "  JOIN meta m2 ON m2.file_hash = mi2.file_hash"
                "  WHERE m2.path = items.path"
                f"    AND ({clause_ex_like})"
                ")"
            )
            params.extend(values_ex)

        # ディレクトリ絞り込みは items.path で
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
        conditions, params, _ = self.build_conditions(normalize_path_func, require_keys=self.require_keys)
        if conditions is None:
            return (None, None)
        where = ('WHERE ' + ' AND '.join(conditions)) if conditions else ''
        sql = f"""
            SELECT path, key, value
            FROM (
                SELECT m.path AS path, m.file_hash AS file_hash, mi.key AS key, mi.value AS value
                FROM meta AS m
                JOIN meta_info AS mi ON mi.file_hash = m.file_hash
                UNION ALL
                SELECT m.path AS path, m.file_hash AS file_hash, t.key AS key, t.value AS value
                FROM meta AS m
                JOIN tags AS t ON t.file_hash = m.file_hash
            ) AS items
            {where}
        """
        return (sql, params)

    @profiler.profile
    def to_path_query(self, normalize_path_func):
        conditions, params, _ = self.build_conditions(normalize_path_func, require_keys=self.require_keys)
        if conditions is None:
            return (None, None)
        where = ('WHERE ' + ' AND '.join(conditions)) if conditions else ''
        sql = f"""
            SELECT DISTINCT path
            FROM (
                SELECT m.path AS path, m.file_hash AS file_hash, mi.key AS key, mi.value AS value
                FROM meta AS m
                JOIN meta_info AS mi ON mi.file_hash = m.file_hash
                UNION ALL
                SELECT m.path AS path, m.file_hash AS file_hash, t.key AS key, t.value AS value
                FROM meta AS m
                JOIN tags AS t ON t.file_hash = m.file_hash
            ) AS items
            {where}
        """
        return (sql, params)

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
                
            self._apply_connection_pragmas(conn)
            self.conn = conn
            return True
        except sqlite3.OperationalError as e:
            logger.warning(f'DB connection failed: {e}')
            return False

    def _apply_connection_pragmas(self, conn: sqlite3.Connection) -> None:
        try:
            cur = conn.cursor()
            cur.executescript("""
                PRAGMA temp_store=MEMORY;
            """)
        except Exception as e:
            logger.warning(f'PRAGMA apply failed (non-fatal): {e}')

    def _normalize_path(self, path):
        return normalize_path(path)

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
            return ([], [], [])
        sort_column, order = self._build_sort_clause(sort_by, ascending)

        cur.execute("CREATE TEMP TABLE IF NOT EXISTS _tmp_paths(path TEXT PRIMARY KEY) WITHOUT ROWID")
        cur.execute("DELETE FROM _tmp_paths")
        for i in range(0, len(paths), batch_size):
            cur.executemany("INSERT INTO _tmp_paths(path) VALUES (?)", [(p,) for p in paths[i:i+batch_size]])

        # ランダム
        if sort_by == 'random':
            rows = cur.execute(
                """
                SELECT m.path, m.source, m.aspect_ratio
                FROM meta AS m
                JOIN _tmp_paths t ON t.path = m.path
                """
            ).fetchall()
            rows = list(rows)
            shuffle(rows)
            return ([row['path'] for row in rows], [row['source'] for row in rows], [row['aspect_ratio'] for row in rows])

        # 並び替えカラムがある場合：エイリアスを使わずに直接 ORDER BY
        if sort_column:
            rows = cur.execute(
                f"""
                SELECT m.path, m.source, m.aspect_ratio
                FROM meta AS m
                JOIN _tmp_paths t ON t.path = m.path
                ORDER BY m."{sort_column}" {order}
                """
            ).fetchall()
            return ([row['path'] for row in rows], [row['source'] for row in rows], [row['aspect_ratio'] for row in rows])

        # 並び替え無し
        rows = cur.execute(
            """
            SELECT m.path, m.source, m.aspect_ratio
            FROM meta AS m
            JOIN _tmp_paths t ON t.path = m.path
            """
        ).fetchall()
        return ([row['path'] for row in rows], [row['source'] for row in rows], [row['aspect_ratio'] for row in rows])


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
        self.explain_query_plan(query)
        if not self._connect_if_needed():
            return ([], [], [])
        cur = self.conn.cursor()
        sql, params = query.to_path_query(self._normalize_path)
        if not sql:
            return ([], [], [])
        try:
            rows = cur.execute(sql, params).fetchall()
        except sqlite3.DatabaseError as e:
            logger.error(f'DB query failed: {e}')
            return ([], [], [])
        paths = [row['path'] for row in rows]
        return self._fetch_paths_with_aspect_ratio(cur, paths, query.sort_by, query.ascending)
    
    @profiler.profile
    def get_combined(self, queries):
        if not self._connect_if_needed():
            return ([], [])
        cur = self.conn.cursor()

        subqueries = []
        params = []
        for q in queries:
            sql, p = q.to_path_query(self._normalize_path)
            if not sql:
                if q.append_mode == 'AND':
                    return ([], [])
                continue
            # to_path_query は "SELECT DISTINCT path FROM (...items...)" なので
            # そのまま括って使える
            subqueries.append(f"({sql})")
            params.extend(p)

        if not subqueries:
            return ([], [])

        # 先頭を土台に、以降を AND=INTERSECT / OR=UNION で合成
        combined = subqueries[0]
        for i in range(1, len(subqueries)):
            op = "INTERSECT" if queries[i].append_mode == 'AND' else "UNION"
            combined = f"({combined}) {op} {subqueries[i]}"

        sort_col, order = self._build_sort_clause(queries[-1].sort_by, queries[-1].ascending)
        if sort_col:
            final_query = f"""
                SELECT m.path, m.aspect_ratio
                FROM meta AS m
                JOIN ({combined}) AS c ON c.path = m.path
                ORDER BY m."{sort_col}" {order}
            """
        else:
            final_query = f"""
                SELECT m.path, m.aspect_ratio
                FROM meta AS m
                JOIN ({combined}) AS c ON c.path = m.path
            """

        rows = cur.execute(final_query, params).fetchall()
        if queries[-1].sort_by == 'random':
            rows = list(rows); shuffle(rows)
        return ([row['path'] for row in rows], [row['aspect_ratio'] for row in rows])


    @profiler.profile
    def list_all_keys(self, query, sort_by_freq=False):
        if not self._connect_if_needed():
            return []
        cur = self.conn.cursor()
        filters, params, _ = query.build_conditions(self._normalize_path, require_keys=False)
        where = f"WHERE {' AND '.join(filters)}" if filters else ''
        order = 'ORDER BY freq DESC' if sort_by_freq else 'ORDER BY key'
        sql = f"""
            SELECT key, COUNT(*) AS freq
            FROM (
                SELECT m.path AS path, m.file_hash AS file_hash, mi.key AS key, mi.value AS value
                FROM meta AS m
                JOIN meta_info AS mi ON mi.file_hash = m.file_hash
                UNION ALL
                SELECT m.path AS path, m.file_hash AS file_hash, t.key AS key, t.value AS value
                FROM meta AS m
                JOIN tags AS t ON t.file_hash = m.file_hash
            ) AS items
            {where}
            GROUP BY key
            {order}
        """
        rows = cur.execute(sql, params).fetchall()
        return [(row['key'], row['freq']) for row in rows]

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
            logger.info('========= SQLite Execution Plan =========')
            for line in plan_lines:
                if not "USING INDEX" in line:
                    logger.warning(f"[NOT USING INDEX CHEK IT OUT]: {line}")
                else:
                    logger.info(line)
        except Exception as e:
            logger.warning(f'EXPLAIN QUERY PLAN failed: {e}')
            return None
        
    @profiler.profile
    def get_meta_info_by_path(self, path):
        if not self._connect_if_needed():
            return {}
        cur = self.conn.cursor()
        norm_path = self._normalize_path(path)
        row = cur.execute("SELECT file_hash FROM meta WHERE path = ?", (norm_path,)).fetchone()
        if not row:
            return {}
        fid = row["file_hash"]
        rows = cur.execute("SELECT key, value FROM meta_info WHERE file_hash = ?", (fid,)).fetchall()
        return {r["key"]: r["value"] for r in rows}
    
    @profiler.profile
    def get_tags_by_path(self, path):
        if not self._connect_if_needed():
            return {}
        cur = self.conn.cursor()
        norm_path = self._normalize_path(path)
        row = cur.execute("SELECT file_hash FROM meta WHERE path = ?", (norm_path,)).fetchone()
        if not row:
            return {}
        fid = row["file_hash"]
        rows = cur.execute("SELECT key, value FROM tags WHERE file_hash = ?", (fid,)).fetchall()
        return {r["key"]: r["value"] for r in rows}

    @profiler.profile
    def get_meta_by_path(self, path):
        if not self._connect_if_needed():
            return {}
        cur = self.conn.cursor()
        norm_path = self._normalize_path(path)
        row = cur.execute(
            "SELECT * FROM meta WHERE path = ?",
            (norm_path,)
        ).fetchone()
        return dict(row) if row else {}
    
    def get_metas(self, path):
        return [self.get_meta_by_path(path), self.get_tags_by_path(path), self.get_meta_info_by_path(path)]