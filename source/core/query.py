import os
import sqlite3
from operator import attrgetter
from random import shuffle
from pathlib import Path
from ..common import normalize_path
from ..profiling import init_env
logger, profiler = init_env()

class MetaQuery:
    def __init__(self, keys=None, keywords=None, query_mode="LIKE", directories=None,
                 keyword_mode="OR", sort_by="name", ascending=True,
                 append_mode="OR", splittext=None, only_direct_children=False):
        self.keys = keys
        self.keywords = keywords
        self.query_mode = query_mode
        self.directories = directories  # Can be str or List[str]
        self.keyword_mode = keyword_mode
        self.sort_by = sort_by
        self.ascending = ascending
        self.append_mode = append_mode
        self.splittext = splittext
        self.only_direct_children = only_direct_children

    def __eq__(self, other):
        if not isinstance(other, MetaQuery):
            return NotImplemented
        return (
            self.keys == other.keys and
            self.keywords == other.keywords and
            self.query_mode == other.query_mode and
            self.directories == other.directories and
            self.keyword_mode == other.keyword_mode and
            self.sort_by == other.sort_by and
            self.ascending == other.ascending and
            self.append_mode == other.append_mode and
            self.splittext == other.splittext and
            self.only_direct_children == other.only_direct_children
        )

    def __hash__(self):
        # 必要であれば hashable にする（例：setやdictのキーにする場合）
        return hash((
            tuple(self.keys or []),
            tuple(self.keywords or []),
            self.query_mode,
            tuple(self.directories or []),
            self.keyword_mode,
            self.sort_by,
            self.ascending,
            self.append_mode,
            self.splittext,
            self.only_direct_children,
        ))

    @profiler.profile
    def normalize_inputs(self):
        keys = [self.keys] if isinstance(self.keys, str) else (self.keys or [])
        keywords = self.keywords
        if isinstance(keywords, str):
            keywords = [w.strip() for w in keywords.split(self.splittext)] if self.splittext else [keywords]
        include = [kw for kw in (keywords or []) if not kw.startswith("-")]
        exclude = [kw[1:] for kw in (keywords or []) if kw.startswith("-")]
        return keys, include, exclude

    @profiler.profile
    def build_conditions(self, normalize_path_func, require_keys=True):
        keys, include_keywords, exclude_keywords = self.normalize_inputs()
        if require_keys and not keys:
            return None, None, None

        conditions = []
        params = []

        if keys:
            key_placeholders = ",".join("?" for _ in keys)
            conditions.append(f"key IN ({key_placeholders})")
            params.extend(keys)

        def match_clause(field, keywords, operator):
            if not keywords:
                return "", []
            mode = self.query_mode.upper()
            clause_format = f"{field} {'GLOB' if mode == 'GLOB' else 'LIKE'} ?"
            values = [f"*{kw}*" if mode == 'GLOB' else f"%{kw}%" for kw in keywords]
            clauses = [clause_format for _ in keywords]
            return f" {operator} ".join(clauses), values

        if include_keywords:
            clause, values = match_clause("value", include_keywords, self.keyword_mode)
            conditions.append(f"({clause})")
            params.extend(values)

        if exclude_keywords:
            clause, values = match_clause("value", exclude_keywords, "OR")
            conditions.append(f"path NOT IN (SELECT path FROM meta_info WHERE {clause})")
            params.extend(values)

        if self.directories:
            dirs = [str(Path(d).resolve()) for d in self.directories if isinstance(d, str) and d]
            
            for d in dirs:
                norm_dir = normalize_path_func(str(d))
                prefix = norm_dir + '/' if norm_dir else ''
                if self.only_direct_children:
                    conditions.append("path LIKE ?")
                    params.append(f"{prefix}%")
                    conditions.append("path NOT LIKE ?")
                    params.append(f"{prefix}%/%")
                else:
                    conditions.append("path LIKE ?")
                    params.append(f"{prefix}%")

        return conditions, params, keys

    @profiler.profile
    def to_sql(self, normalize_path_func):
        conditions, params, keys = self.build_conditions(normalize_path_func)
        if not keys:
            return None, None
        return f"SELECT path, key, value FROM meta_info WHERE {' AND '.join(conditions)}", params

    @profiler.profile
    def to_path_query(self, normalize_path_func):
        conditions, params, keys = self.build_conditions(normalize_path_func)
        if not keys:
            return None, None
        return f"SELECT DISTINCT path FROM meta_info WHERE {' AND '.join(conditions)}", params


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
            conn = sqlite3.connect(
                f"file:{self.db_path}?mode=ro",
                uri=True,
                check_same_thread=False
            )
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='meta_info'")
            if not cur.fetchone():
                logger.warning("Table 'meta_info' not found in DB.")
                return False
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='images'")
            if not cur.fetchone():
                logger.warning("Table 'images' not found in DB.")
                return False
            self.conn = conn
            return True
        except sqlite3.OperationalError as e:
            logger.warning(f"DB connection failed: {e}")
            return False

    def _normalize_path(self, path):
        return path.replace('\\', '/').rstrip('/')

    @profiler.profile
    def _build_sort_clause(self, sort_by, ascending):
        sort_column_map = {
            "name": "meta.path",
            "created": "created",
            "modified": "mtime",
            "size": "size",
            "collected": "collected_at",
            "random": None,
        }
        sort_column = sort_column_map.get(sort_by)
        order = "ASC" if ascending else "DESC"
        return sort_column, order

    @profiler.profile
    def _fetch_paths_with_aspect_ratio(self, cur, paths, sort_by, ascending, batch_size=700):
        if not paths:
            return [], []

        sort_column, order = self._build_sort_clause(sort_by, ascending)

        all_rows = []
            
        for i in range(0, len(paths), batch_size):
            batch = paths[i:i + batch_size]
            placeholders = ",".join("?" for _ in batch)
            if sort_column:
                query = f"""
                    SELECT meta.path, aspect_ratio, {sort_column} AS sort_value
                    FROM meta
                    WHERE meta.path IN ({placeholders})
                """
            else:
                query = f"""
                    SELECT meta.path, aspect_ratio
                    FROM meta
                    WHERE meta.path IN ({placeholders})
                """
            rows = cur.execute(query, batch).fetchall()
            all_rows.extend(rows)

        if sort_by == "random":
            shuffle(all_rows)
        else:
            # sort_value に基づいてソート
            all_rows.sort(key=lambda row: row["sort_value"], reverse=not ascending)

        return [row["path"] for row in all_rows], [row["aspect_ratio"] for row in all_rows]

    @profiler.profile
    def search(self, query):
        if not self._connect_if_needed():
            return []
        cur = self.conn.cursor()
        sql, params = query.to_sql(normalize_path)
        if not sql:
            return []
        rows = cur.execute(sql, params).fetchall()
        return [(row["path"], row["key"], row["value"]) for row in rows]

    @profiler.profile
    def get(self, query):
        if not self._connect_if_needed():
            return [], []
        cur = self.conn.cursor()
        sql, params = query.to_path_query(self._normalize_path)
        if not sql:
            return [], []
        try:
            rows = cur.execute(sql, params).fetchall()
        except sqlite3.DatabaseError as e:
            logger.error(f"DB query failed: {e}")
            return [], []
        paths = [row["path"] for row in rows]
        return self._fetch_paths_with_aspect_ratio(cur, paths, query.sort_by, query.ascending)

    @profiler.profile
    def get_combined(self, queries):
        if not self._connect_if_needed():
            return [], []
        cur = self.conn.cursor()
        subqueries = []

        for q in queries:
            sql, params = q.to_path_query(normalize_path)
            if not sql:
                if q.append_mode == "AND":
                    return [], []
                continue
            subqueries.append((sql, params, q.append_mode))

        if not subqueries:
            return [], []

        combined_sql, combined_params = subqueries[0][0], subqueries[0][1]
        for sq, params, mode in subqueries[1:]:
            op = "INTERSECT" if mode == "AND" else "UNION"
            combined_sql = f"({combined_sql}) {op} ({sq})"
            combined_params.extend(params)

        sort_col, order = self._build_sort_clause(queries[-1].sort_by, queries[-1].ascending)
        if sort_col:
            final_query = f"""
                SELECT meta.path, aspect_ratio
                FROM meta
                JOIN images ON meta.path = images.path
                WHERE meta.path IN ({combined_sql})
                ORDER BY {sort_col} {order}
            """
        else:
            final_query = f"""
                SELECT meta.path, aspect_ratio
                FROM meta
                JOIN images ON meta.path = images.path
                WHERE meta.path IN ({combined_sql})
            """
            
        rows = cur.execute(final_query, combined_params).fetchall()
        return [row["path"] for row in rows], [row["aspect_ratio"] for row in rows]

    @profiler.profile
    def list_all_keys(self, query, sort_by_freq=False, include_freq=False):
        if not self._connect_if_needed():
            return []
        cur = self.conn.cursor()
        filters, params, _ = query.build_conditions(normalize_path, require_keys=False)

        if filters is None:
            return []

        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        group_order_clause = "GROUP BY key ORDER BY " + ("freq DESC" if sort_by_freq else "key")

        query_sql = f"SELECT key, COUNT(*) as freq FROM meta_info {where_clause} {group_order_clause}"
        rows = cur.execute(query_sql, params).fetchall()
        return [(row["key"], row["freq"]) if include_freq else row["key"] for row in rows]

    @profiler.profile
    def explain_query_plan(self, query: MetaQuery):
        if not self._connect_if_needed():
            logger.warning("DB接続失敗：explain_query_plan スキップ")
            return None

        sql, params = query.to_sql(normalize_path)
        if not sql:
            logger.info("無効なクエリのため EXPLAIN QUERY PLAN をスキップ")
            return None

        explain_sql = f"EXPLAIN QUERY PLAN {sql}"
        try:
            cur = self.conn.cursor()
            rows = cur.execute(explain_sql, params).fetchall()
            plan_lines = [f"[{row['id']}] {row['detail']}" for row in rows]
            logger.info("=== SQLite 実行計画 ===")
            for line in plan_lines:
                logger.info(line)
        except Exception as e:
            logger.warning(f"EXPLAIN QUERY PLAN failed: {e}")
            return None
