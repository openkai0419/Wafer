from __future__ import annotations

from ...core.common.virtual_paths import source_path
from ...core.profiling import profiler
from ...core.db.file_db import schema_columns
from ...core.db.query import _kv_sort_join, ALL_PATHS_SQL, SYSTEM_FILE_HASH_KEY, STANDARD_KEYS_FILES, STANDARD_KEYS_SOURCES, where_clause


class SearchComposer:
    @profiler.profile
    def execute(self, engine, filter_entries, sort_plugin, ascending):
        if not engine._connect_if_needed():
            return [], [], []

        path_sql, path_params = self.compose_path_query(engine, filter_entries)
        post_filters = [(filter_cls, params) for filter_cls, params, _ in filter_entries if filter_cls.has_post_filter()]
        if not post_filters and "sort_rows" not in vars(sort_plugin) and not getattr(sort_plugin, "META_KEY", None):
            return self._fetch_paths(engine, path_sql, path_params, getattr(sort_plugin, "SORT_COLUMN", None), ascending)

        columns = ["path", "source", "aspect_ratio"]
        for filter_cls, _params, _ in filter_entries:
            for col in filter_cls.required_columns():
                if col not in columns:
                    columns.append(col)

        rows = self._fetch(engine, columns, path_sql, path_params, sort_plugin, ascending)

        for filter_cls, params in post_filters:
            rows = filter_cls.post_filter(params, rows)

        return (
            [r["path"] for r in rows],
            [r["source"] for r in rows],
            [r["aspect_ratio"] or 1.0 for r in rows],
        )

    @profiler.profile
    def list_all_keys(self, engine, filter_entries, sort_by_freq=False):
        if not engine._connect_if_needed():
            return []

        scope_where, scope_params = self.compose_path_scope(engine, filter_entries, "path")
        file_from = "files AS i JOIN sources AS s ON s.source = i.source"

        meta_where = where_clause([*scope_where, 'mi."key" <> ?'])
        meta_sql = f'SELECT mi."key", COUNT(*) FROM meta_info AS mi{meta_where} GROUP BY mi."key"'
        meta_counts = dict(tuple(r) for r in engine.fetch(meta_sql, [*scope_params, SYSTEM_FILE_HASH_KEY]))
        hash_counts = f"SELECT s.file_hash, COUNT(*) AS n FROM {file_from}{where_clause(scope_where)} GROUP BY s.file_hash"
        tag_sql = f'SELECT t."key", SUM(c.n) FROM ({hash_counts}) AS c JOIN tags AS t ON t.file_hash = c.file_hash GROUP BY t."key"'
        tag_counts = dict(tuple(r) for r in engine.fetch(tag_sql, scope_params))

        counts = {**meta_counts, **tag_counts}
        shared_keys = sorted(meta_counts.keys() & tag_counts.keys())
        if shared_keys:
            key_list = f"IN ({', '.join('?' * len(shared_keys))})"
            meta_key_where = where_clause([*scope_where, f'mi."key" {key_list}'])
            tag_key_where = where_clause([*scope_where, f't."key" {key_list}'])
            meta_paths = f'SELECT mi."key", mi.path FROM meta_info AS mi{meta_key_where}'
            tag_paths = f'SELECT t."key", i.path FROM {file_from} JOIN tags AS t ON t.file_hash = s.file_hash{tag_key_where}'
            shared_sql = f'SELECT "key", COUNT(*) FROM ({meta_paths} UNION {tag_paths}) GROUP BY "key"'
            counts.update(tuple(r) for r in engine.fetch(shared_sql, [*scope_params, *shared_keys, *scope_params, *shared_keys]))

        std_keys = [k for k in STANDARD_KEYS_FILES if k != "path"]
        std_columns = ["COUNT(*)", *(f'COUNT(i."{k}")' for k in std_keys), *(f'COUNT(s."{k}")' for k in STANDARD_KEYS_SOURCES), "COUNT(s.source)"]
        std_sql = f"SELECT {', '.join(std_columns)} FROM files AS i LEFT JOIN sources AS s ON s.source = i.source{where_clause(scope_where)}"
        std_counts = engine.fetch(std_sql, scope_params)[0]
        for key, n in zip(["path", *std_keys, *STANDARD_KEYS_SOURCES, SYSTEM_FILE_HASH_KEY], std_counts):
            if n:
                counts[key] = n

        if sort_by_freq:
            return sorted(counts.items(), key=lambda kv: -kv[1])
        return sorted(counts.items())

    @staticmethod
    def _combine(valid_queries):
        if not valid_queries:
            return ALL_PATHS_SQL, []
        if len(valid_queries) == 1:
            sql, bind, _op = valid_queries[0]
            return sql, list(bind)

        operands = [(sql, list(bind)) for sql, bind, _op in valid_queries]
        operators = [SearchComposer._normalize_operator(op) for _sql, _bind, op in valid_queries[1:]]

        def has_operator(index, value):
            operator_index = index - 1
            return operator_index < len(operators) and operators[operator_index] == value

        def parse_operand(index):
            return operands[index], index + 1

        def parse_and(index):
            left, index = parse_operand(index)
            while has_operator(index, "AND"):
                right, index = parse_operand(index)
                left = SearchComposer._join_path_sets(left, "INTERSECT", right)
            return left, index

        def parse_or(index):
            left, index = parse_and(index)
            while has_operator(index, "OR"):
                right, index = parse_and(index)
                left = SearchComposer._join_path_sets(left, "UNION", right)
            return left, index

        def parse_not(index):
            left, index = parse_or(index)
            if has_operator(index, "NOT"):
                right, index = parse_not(index)
                left = SearchComposer._join_path_sets(left, "EXCEPT", right)
            return left, index

        return parse_not(0)[0]

    @staticmethod
    def _normalize_operator(op):
        operator = str(op or "OR").upper()
        return operator if operator in {"AND", "OR", "NOT"} else "OR"

    @staticmethod
    def _join_path_sets(left, operator, right):
        left_sql, left_params = left
        right_sql, right_params = right
        if operator == "INTERSECT" and left_sql == ALL_PATHS_SQL:
            return right
        if operator == "INTERSECT" and right_sql == ALL_PATHS_SQL:
            return left
        if operator == "UNION" and ALL_PATHS_SQL in (left_sql, right_sql):
            return ALL_PATHS_SQL, []
        sql = f"SELECT path FROM ({left_sql}) AS _left {operator} SELECT path FROM ({right_sql}) AS _right"
        return sql, [*left_params, *right_params]

    @staticmethod
    def _compose_parts(engine, filter_entries, column):
        row_queries = []
        conditions = []
        condition_params = []
        for filter_cls, params, op in filter_entries:
            if filter_cls.QUERY_SCOPE == "global":
                condition, bind = filter_cls.build_path_condition(params, engine._normalize_path, column)
                if condition is not None:
                    conditions.append(condition)
                    condition_params.extend(bind)
                continue
            sql, bind = filter_cls.build_path_query(params, engine._normalize_path)
            if sql is not None:
                row_queries.append((sql, bind, op))
        row_sql, row_params = SearchComposer._combine(row_queries)
        return row_sql, row_params, conditions, condition_params

    @staticmethod
    def compose_path_scope(engine, filter_entries, column):
        row_sql, row_params, conditions, condition_params = SearchComposer._compose_parts(engine, filter_entries, column)
        if row_sql == ALL_PATHS_SQL:
            return conditions, condition_params
        return [f"{column} IN ({row_sql})", *conditions], [*row_params, *condition_params]

    @staticmethod
    def compose_path_query(engine, filter_entries):
        row_sql, row_params, conditions, condition_params = SearchComposer._compose_parts(engine, filter_entries, "path")
        if not conditions:
            return row_sql, row_params
        if row_sql == ALL_PATHS_SQL:
            return f"SELECT path FROM files{where_clause(conditions)}", condition_params
        return f"SELECT path FROM ({row_sql}){where_clause(conditions)}", [*row_params, *condition_params]

    @staticmethod
    @profiler.profile
    def _fetch_paths(engine, path_sql, params, sort_column, ascending):
        tables = "files AS i"
        sort_table = "i" if sort_column in schema_columns("files") else "s"
        if sort_column and sort_table == "s":
            tables += " JOIN sources AS s ON s.source = i.source"
        if path_sql == ALL_PATHS_SQL:
            sql, params = f"SELECT i.path, i.aspect_ratio FROM {tables}", []
        else:
            sql = f"SELECT i.path, i.aspect_ratio FROM {tables} JOIN ({path_sql}) AS f ON f.path = i.path"
        if sort_column:
            order = "ASC" if ascending else "DESC"
            sql += f" ORDER BY {sort_table}.{sort_column} {order}, i.path {order}"
        cursor = engine.conn.cursor()
        cursor.row_factory = None
        rows = cursor.execute(sql, params).fetchall()
        paths = [r[0] for r in rows]
        return paths, [source_path(p) for p in paths], [r[1] or 1.0 for r in rows]

    @staticmethod
    def _source_rows(path_sql):
        if path_sql == ALL_PATHS_SQL:
            return "files_full AS m"
        return f"files_full AS m JOIN ({path_sql}) AS s USING(path)"

    @profiler.profile
    def _fetch(self, engine, columns, path_sql, params, sort_plugin, ascending):
        rows_from = self._source_rows(path_sql)
        sort_column = getattr(sort_plugin, "SORT_COLUMN", None)
        meta_key = getattr(sort_plugin, "META_KEY", None)
        has_custom_sort = "sort_rows" in vars(sort_plugin)
        cols = list(columns)
        if sort_column and sort_column not in cols:
            cols.append(sort_column)
        col_str = ", ".join(f"m.{c}" for c in cols)
        if sort_column:
            if has_custom_sort:
                rows = list(engine.fetch(f"SELECT {col_str} FROM {rows_from}", params))
                return sort_plugin.sort_rows(rows, ascending)
            order = "ASC" if ascending else "DESC"
            return engine.fetch(f"SELECT {col_str} FROM {rows_from} ORDER BY m.{sort_column} {order}, m.path {order}", params)
        if has_custom_sort:
            if meta_key:
                kv_join, kv_select, _, kv_params = _kv_sort_join(meta_key, engine.conn)
                rows = list(engine.fetch(f"SELECT {col_str}{kv_select} FROM {rows_from}{kv_join}", [*params, *kv_params]))
            else:
                rows = list(engine.fetch(f"SELECT {col_str} FROM {rows_from}", params))
            return sort_plugin.sort_rows(rows, ascending)
        if meta_key:
            order = "ASC" if ascending else "DESC"
            kv_join, _, kv_order, kv_params = _kv_sort_join(meta_key, engine.conn)
            return engine.fetch(f"SELECT {col_str} FROM {rows_from}{kv_join} ORDER BY {kv_order} {order}, m.path {order}", [*params, *kv_params])
        return engine.fetch(f"SELECT {col_str} FROM {rows_from}", params)
