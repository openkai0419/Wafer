import os
import sqlite3
from pathlib import Path
from random import shuffle
from typing import Sequence
from functools import lru_cache

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
    def build_conditions(
        self,
        normalize_path_func,
        *,
        alias_m: str = "k",
        alias_k: str = "k",
        require_keys: bool = True,
    ):
        keys, include_keywords, exclude_keywords = self.normalize_inputs()
        if require_keys and (not keys):
            return None, None  # 呼び出し側でハンドリング（=無効クエリ）

        def esc_like(s: str) -> str:
            return s.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')

        conditions: list[str] = []
        params: list[str] = []

        # keys
        if keys:
            placeholders = ",".join("?" for _ in keys)
            conditions.append(f'{alias_k}."key" IN ({placeholders})')
            params.extend(keys)

        # include
        def match_clause(field: str, keywords: list[str], op: str):
            if not keywords:
                return "", []
            if self.query_mode.upper() == "GLOB":
                clauses = [f"{field} GLOB ?" for _ in keywords]
                values = [f"*{kw}*" for kw in keywords]
            else:
                clauses = [f"{field} LIKE ? ESCAPE '\\'" for _ in keywords]
                values = [f"%{esc_like(kw)}%" for kw in keywords]
            return (" " + op + " ").join(clauses), values

        if include_keywords:
            clause, values = match_clause(f'{alias_k}."value"', include_keywords, self.keyword_mode)
            conditions.append(f"({clause})")
            params.extend(values)

        # exclude（同一 path のレコードにその語が存在しないこと）
        if exclude_keywords:
            clause_ex, values_ex = match_clause('k2."value"', exclude_keywords, "OR")
            if keys:
                placeholders = ",".join("?" for _ in keys)
                conditions.append(
                    "NOT EXISTS ("
                    "  SELECT 1"
                    "  FROM kv_meta k2"
                    f"  WHERE k2.path = {alias_m}.path"
                    f"    AND k2.\"key\" IN ({placeholders})"
                    f"    AND ({clause_ex})"
                    ")"
                )
                params.extend(keys)
            else:
                conditions.append(
                    "NOT EXISTS ("
                    "  SELECT 1"
                    "  FROM kv_meta k2"
                    f"  WHERE k2.path = {alias_m}.path"
                    f"    AND ({clause_ex})"
                    ")"
                )
            params.extend(values_ex)

        # directories
        if self.directories:
            dirs = [str(Path(d).resolve()) for d in self.directories if isinstance(d, str) and d]
            dir_clauses, dir_params = [], []
            for d in dirs:
                nd = normalize_path_func(str(d))
                prefix = (nd + "/") if nd else ""
                esc_prefix = prefix.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
                if self.only_direct_children:
                    dir_clauses.append(f"({alias_m}.path LIKE ? ESCAPE '\\' AND {alias_m}.path NOT LIKE ? ESCAPE '\\')")
                    dir_params.extend([f"{esc_prefix}%", f"{esc_prefix}%/%"])
                else:
                    dir_clauses.append(f"{alias_m}.path LIKE ? ESCAPE '\\'")
                    dir_params.append(f"{esc_prefix}%")
            if dir_clauses:
                conditions.append("(" + " OR ".join(dir_clauses) + ")")
                params.extend(dir_params)

        return conditions, params


    @profiler.profile
    def _is_fastpath_simple_keys(self):
        # keys があり、include/exclude なし、directories なし、only_direct_children 無関係、
        # require_keys が True（既定）であるケースを高速経路に乗せる
        keys, include_keywords, exclude_keywords = self.normalize_inputs()
        return (
            self.require_keys and
            keys and
            not include_keywords and
            not exclude_keywords and
            not self.directories
        )

    @profiler.profile
    def _make_kv_subquery(self, normalize_path_func, *, require_keys_override: bool | None = None):
        rk = self.require_keys if require_keys_override is None else require_keys_override
        conditions, params = self.build_conditions( normalize_path_func, alias_m="k", alias_k="k", require_keys=rk)
        if conditions is None:
            return (None, [])

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        subquery = f"""
            SELECT k.path AS path, k.file_hash AS file_hash, k."key" AS "key", k."value" AS "value"
            FROM kv_meta AS k
            {where}
        """
        return (subquery, params)

    @profiler.profile
    def to_sql(self, normalize_path_func):
        if self._is_fastpath_simple_keys():
            keys = [self.keys] if isinstance(self.keys, str) else list(self.keys)
            ph = ",".join("?" for _ in keys)
            sql = f"""
                SELECT k.path AS path, k."key" AS "key", k."value" AS "value"
                FROM kv_meta AS k
                WHERE k."key" IN ({ph})
            """
            return (sql, keys)

        q, p = self._make_kv_subquery(normalize_path_func)
        if not q:
            return (None, None)
        sql = f'''SELECT path, "key", "value" FROM ({q}) AS items'''
        return (sql, p)

    @profiler.profile
    def to_path_query(self, normalize_path_func):
        if self._is_fastpath_simple_keys():
            keys = [self.keys] if isinstance(self.keys, str) else list(self.keys)
            ph = ",".join("?" for _ in keys)
            sql = f"""
                SELECT DISTINCT k.path AS path
                FROM kv_meta AS k
                WHERE k."key" IN ({ph})
            """
            return (sql, keys)

        q, p = self._make_kv_subquery(normalize_path_func)
        if not q:
            return (None, None)
        sql = f"""SELECT path FROM ({q}) AS items GROUP BY path"""
        return (sql, p)



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

            required = ('meta_info', "tags", 'meta', 'kv_meta')
            for name in required:
                cur.execute("SELECT name FROM sqlite_master WHERE name=?", (name,))
                if not cur.fetchone():
                    logger.warning(f"Required table/view '{name}' not found in DB.")
                    conn.close()
                return False
                
            self._apply_connection_pragmas(conn)
            self.conn = conn
            return True
        except sqlite3.OperationalError as e:
            logger.warning(f'DB connection failed: {e}')
            return False

    @profiler.profile
    def _apply_connection_pragmas(self, conn: sqlite3.Connection) -> None:
        try:
            cur = conn.cursor()
            cur.executescript("""
                PRAGMA query_only=ON;
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

        all_rows = []
        for i in range(0, len(paths), batch_size):
            chunk = paths[i:i+batch_size]
            placeholders = ",".join("?" for _ in chunk)

            if sort_by == 'random':
                rows = cur.execute(
                    f"""
                    SELECT m.path, m.source, m.aspect_ratio
                    FROM meta AS m
                    WHERE m.path IN ({placeholders})
                    """,
                    chunk
                ).fetchall()
                all_rows.extend(rows)
                continue

            if sort_column:
                rows = cur.execute(
                    f"""
                    SELECT m.path, m.source, m.aspect_ratio
                    FROM meta AS m
                    WHERE m.path IN ({placeholders})
                    ORDER BY m."{sort_column}" {order}
                    """,
                    chunk
                ).fetchall()
            else:
                rows = cur.execute(
                    f"""
                    SELECT m.path, m.source, m.aspect_ratio
                    FROM meta AS m
                    WHERE m.path IN ({placeholders})
                    """,
                    chunk
                ).fetchall()

            all_rows.extend(rows)

        if sort_by == 'random':
            all_rows = list(all_rows)
            shuffle(all_rows)

        return (
            [r['path'] for r in all_rows],
            [r['source'] for r in all_rows],
            [r['aspect_ratio'] for r in all_rows],
        )


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
    def fetch(self, sql, params):
        cur = self.conn.cursor()
        return cur.execute(sql,params).fetchall()

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
            rows = self.fetch(sql, params)
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

        # ★ keys 未指定でも動くように require_keys=False
        q, p = query._make_kv_subquery(self._normalize_path, require_keys_override=False)
        if not q:
            return []

        order = "ORDER BY freq DESC" if sort_by_freq else "ORDER BY key"
        sql = f"""
            SELECT key, COUNT(*) AS freq
            FROM (
                {q}
            ) AS items
            GROUP BY key
            {order}
        """
        rows = cur.execute(sql, p).fetchall()
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
        row = cur.execute("SELECT path FROM meta WHERE path = ?", (norm_path,)).fetchone()
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