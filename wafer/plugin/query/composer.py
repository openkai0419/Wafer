from __future__ import annotations

from ...core.profiling import profiler
from ...core.db.query import _kv_sort_join, SYSTEM_FILE_HASH_KEY, STANDARD_KEYS_FILES, STANDARD_KEYS_SOURCES
from .base import BaseFilterPlugin, PathScope


class SearchComposer:
    @profiler.profile
    def execute(self, engine, filter_entries, sort_plugin, ascending):
        if not engine._connect_if_needed():
            return [], [], []

        path_sql, path_params = self._build_path_query(engine, filter_entries)

        columns = ["path", "source", "aspect_ratio"]
        for filter_cls, _params, _ in filter_entries:
            for col in filter_cls.required_columns():
                if col not in columns:
                    columns.append(col)

        rows = self._fetch(engine, columns, path_sql, path_params, sort_plugin, ascending)

        for filter_cls, params, _ in filter_entries:
            if filter_cls.post_filter is not BaseFilterPlugin.post_filter:
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

        path_sql, path_params = self._build_path_query(engine, filter_entries)

        order = "ORDER BY freq DESC" if sort_by_freq else 'ORDER BY "key"'
        std_branch_sqls = []
        std_branch_params = []
        for k in STANDARD_KEYS_FILES:
            if k == "path":
                std_branch_sqls.append('  SELECT mp.path, ? AS "key" FROM matched_paths AS mp')
            else:
                std_branch_sqls.append(f'  SELECT mp.path, ? AS "key" FROM matched_paths AS mp JOIN files AS f ON f.path = mp.path WHERE f."{k}" IS NOT NULL')
            std_branch_params.append(k)
        for k in STANDARD_KEYS_SOURCES:
            std_branch_sqls.append(f'  SELECT mp.path, ? AS "key" FROM matched_paths AS mp JOIN files AS f ON f.path = mp.path JOIN sources AS s ON s.source = f.source WHERE s."{k}" IS NOT NULL')
            std_branch_params.append(k)
        std_branches = " UNION ALL ".join(std_branch_sqls)
        sql = (
            f"WITH matched_paths AS ({path_sql}) "
            f'SELECT "key", COUNT(DISTINCT path) AS freq FROM ('
            f'  SELECT DISTINCT mp.path, kv."key"'
            f"  FROM matched_paths AS mp"
            f"  JOIN meta_info AS kv ON kv.path = mp.path"
            f'  WHERE kv."key" <> ?'
            f"  UNION ALL"
            f'  SELECT DISTINCT mp.path, t."key"'
            f"  FROM matched_paths AS mp"
            f"  JOIN files AS f ON f.path = mp.path"
            f"  JOIN sources AS s ON s.source = f.source"
            f"  JOIN tags AS t ON t.file_hash = s.file_hash"
            f"  UNION ALL"
            f'  SELECT DISTINCT mp.path, ? AS "key"'
            f"  FROM matched_paths AS mp"
            f"  JOIN files AS f ON f.path = mp.path"
            f"  JOIN sources AS s ON s.source = f.source"
            f"  UNION ALL "
            f"{std_branches}"
            f") AS items "
            f'GROUP BY "key" {order}'
        )
        rows = engine.fetch(sql, [*path_params, SYSTEM_FILE_HASH_KEY, SYSTEM_FILE_HASH_KEY, *std_branch_params])
        return [(row["key"], row["freq"]) for row in rows]

    @staticmethod
    def _combine(valid_queries):
        if not valid_queries:
            return "SELECT path FROM files", []
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
        sql = f"SELECT path FROM ({left_sql}) AS _left {operator} SELECT path FROM ({right_sql}) AS _right"
        return sql, [*left_params, *right_params]

    def _build_path_query(self, engine, filter_entries):
        scope = self._build_scope(engine, filter_entries)
        row_queries = []
        for filter_cls, params, op in filter_entries:
            if filter_cls.QUERY_SCOPE == "global":
                continue
            sql, bind = filter_cls.build_path_query(params, engine._normalize_path, scope)
            if sql is not None:
                row_queries.append((sql, bind, op))
        combined_sql, combined_params = self._combine(row_queries)
        if not scope.restricted:
            return combined_sql, combined_params
        cte = PathScope.CTE_NAME
        sql = f"WITH {cte} AS MATERIALIZED ({scope.sql}) SELECT path FROM ({combined_sql}) AS _rw INTERSECT SELECT path FROM {cte}"
        return sql, [*scope.params, *combined_params]

    @staticmethod
    def _build_scope(engine, filter_entries):
        unrestricted = PathScope()
        queries = []
        for filter_cls, params, _op in filter_entries:
            if filter_cls.QUERY_SCOPE != "global":
                continue
            sql, bind = filter_cls.build_path_query(params, engine._normalize_path, unrestricted)
            if sql is not None:
                queries.append((sql, bind))
        if not queries:
            return unrestricted
        return PathScope(" INTERSECT ".join(sql for sql, _ in queries), [b for _, bind in queries for b in bind])

    @profiler.profile
    def _fetch(self, engine, columns, path_sql, params, sort_plugin, ascending):
        sort_column = getattr(sort_plugin, "SORT_COLUMN", None)
        meta_key = getattr(sort_plugin, "META_KEY", None)
        has_custom_sort = "sort_rows" in vars(sort_plugin)
        cols = list(columns)
        if sort_column and sort_column not in cols:
            cols.append(sort_column)
        col_str = ", ".join(f"m.{c}" for c in cols)
        if sort_column:
            if has_custom_sort:
                sql = f"SELECT {col_str} FROM files_full AS m JOIN ({path_sql}) AS s USING(path)"
                rows = list(engine.fetch(sql, params))
                return sort_plugin.sort_rows(rows, ascending)
            order = "ASC" if ascending else "DESC"
            sql = f"SELECT {col_str} FROM files_full AS m JOIN ({path_sql}) AS s USING(path) ORDER BY m.{sort_column} {order}, m.path {order}"
            return engine.fetch(sql, params)
        if has_custom_sort:
            if meta_key:
                kv_join, kv_select, _, kv_params = _kv_sort_join(meta_key, engine.conn)
                sql = f"SELECT {col_str}{kv_select} FROM files_full AS m JOIN ({path_sql}) AS s USING(path){kv_join}"
                rows = list(engine.fetch(sql, [*params, *kv_params]))
            else:
                sql = f"SELECT {col_str} FROM files_full AS m JOIN ({path_sql}) AS s USING(path)"
                rows = list(engine.fetch(sql, params))
            return sort_plugin.sort_rows(rows, ascending)
        if meta_key:
            order = "ASC" if ascending else "DESC"
            kv_join, _, kv_order, kv_params = _kv_sort_join(meta_key, engine.conn)
            sql = f"SELECT {col_str} FROM files_full AS m JOIN ({path_sql}) AS s USING(path){kv_join} ORDER BY {kv_order} {order}, m.path {order}"
            return engine.fetch(sql, [*params, *kv_params])
        sql = f"SELECT {col_str} FROM files_full AS m JOIN ({path_sql}) AS s USING(path)"
        return engine.fetch(sql, params)
