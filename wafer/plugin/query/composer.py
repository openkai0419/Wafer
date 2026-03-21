from __future__ import annotations

from ...utils.profiling import profiler
from ...core.db.query import _kv_sort_join
from .base import BaseFilterPlugin, BaseSortPlugin


class SearchComposer:

    @profiler.profile
    def execute(self, engine, filter_entries, sort_plugin, ascending):
        if not engine._connect_if_needed():
            return [], [], []

        row_queries = []
        global_queries = []
        post_filters = []

        for filter_cls, params, op in filter_entries:
            sql, bind = filter_cls.build_path_query(params, engine._normalize_path)
            if sql is not None:
                if filter_cls.SCOPE == 'global':
                    global_queries.append((sql, bind))
                else:
                    row_queries.append((sql, bind, op))
            if filter_cls.post_filter is not BaseFilterPlugin.post_filter:
                post_filters.append((filter_cls, params))

        combined_sql, combined_params = self._combine(row_queries)
        combined_sql, combined_params = self._apply_global(
            combined_sql, combined_params, global_queries
        )
        if combined_sql is None:
            return [], [], []

        columns = ['path', 'source', 'aspect_ratio']
        for filter_cls, params, _ in filter_entries:
            for col in filter_cls.required_columns():
                if col not in columns:
                    columns.append(col)

        rows = self._fetch(
            engine, columns, combined_sql, combined_params, sort_plugin, ascending
        )

        for filter_cls, params in post_filters:
            rows = filter_cls.post_filter(params, rows)

        return (
            [r['path'] for r in rows],
            [r['source'] for r in rows],
            [r['aspect_ratio'] or 1.0 for r in rows],
        )

    @profiler.profile
    def list_all_keys(self, engine, filter_entries, sort_by_freq=False):
        if not engine._connect_if_needed():
            return []

        row_queries = []
        global_queries = []
        for filter_cls, params, op in filter_entries:
            sql, bind = filter_cls.build_path_query(params, engine._normalize_path)
            if sql is not None:
                if filter_cls.SCOPE == 'global':
                    global_queries.append((sql, bind))
                else:
                    row_queries.append((sql, bind, op))

        combined_sql, combined_params = self._combine(row_queries)
        combined_sql, combined_params = self._apply_global(
            combined_sql, combined_params, global_queries
        )
        if combined_sql is None:
            return []

        order = 'ORDER BY freq DESC' if sort_by_freq else 'ORDER BY "key"'
        sql = (
            f"WITH matched_paths AS ({combined_sql}) "
            f'SELECT "key", COUNT(*) AS freq FROM ('
            f'  SELECT DISTINCT mp.path, kv."key"'
            f"  FROM matched_paths AS mp"
            f"  JOIN meta_info AS kv ON kv.path = mp.path"
            f"  UNION ALL"
            f'  SELECT DISTINCT mp.path, t."key"'
            f"  FROM matched_paths AS mp"
            f"  JOIN files AS f ON f.path = mp.path"
            f"  JOIN sources AS s ON s.source = f.source"
            f"  JOIN tags AS t ON t.file_hash = s.file_hash"
            f") AS items "
            f'GROUP BY "key" {order}'
        )
        rows = engine.fetch(sql, combined_params)
        return [(row['key'], row['freq']) for row in rows]

    @staticmethod
    def _combine(valid_queries):
        if not valid_queries:
            return "SELECT path FROM files", []

        groups = []
        current_sqls = []
        current_params = []

        for sql, bind, op in valid_queries:
            if op == 'AND' and current_sqls:
                current_sqls.append(sql)
                current_params.extend(bind)
            else:
                if current_sqls:
                    group_sql = (
                        " INTERSECT ".join(current_sqls)
                        if len(current_sqls) > 1 else current_sqls[0]
                    )
                    groups.append((group_sql, list(current_params)))
                current_sqls = [sql]
                current_params = list(bind)

        if current_sqls:
            group_sql = (
                " INTERSECT ".join(current_sqls)
                if len(current_sqls) > 1 else current_sqls[0]
            )
            groups.append((group_sql, list(current_params)))

        if len(groups) == 1:
            return groups[0]

        all_sqls = []
        all_params = []
        for sql, params in groups:
            all_sqls.append(sql)
            all_params.extend(params)
        return " UNION ".join(all_sqls), all_params

    @staticmethod
    def _apply_global(combined_sql, combined_params, global_queries):
        if not global_queries:
            return combined_sql, combined_params
        all_params = list(combined_params)
        parts = [f"SELECT path FROM ({combined_sql}) AS _rw"]
        for gsql, gbind in global_queries:
            parts.append(gsql)
            all_params.extend(gbind)
        return " INTERSECT ".join(parts), all_params

    @profiler.profile
    def _fetch(self, engine, columns, path_sql, params, sort_plugin, ascending):
        col_str = ', '.join(f'm.{c}' for c in columns)
        meta_key = sort_plugin.META_KEY
        has_custom_sort = 'sort_rows' in vars(sort_plugin)
        if has_custom_sort:
            if meta_key:
                kv_join, kv_select, _, kv_params = _kv_sort_join(meta_key, engine.conn)
                sql = (
                    f"SELECT {col_str}{kv_select} FROM files_full AS m "
                    f"JOIN ({path_sql}) AS s USING(path){kv_join}"
                )
                rows = list(engine.fetch(sql, [*params, *kv_params]))
            else:
                sql = (
                    f"SELECT {col_str} FROM files_full AS m "
                    f"JOIN ({path_sql}) AS s USING(path)"
                )
                rows = list(engine.fetch(sql, params))
            return sort_plugin.sort_rows(rows, ascending)
        elif meta_key:
            order = 'ASC' if ascending else 'DESC'
            kv_join, _, kv_order, kv_params = _kv_sort_join(meta_key, engine.conn)
            sql = (
                f"SELECT {col_str} FROM files_full AS m "
                f"JOIN ({path_sql}) AS s USING(path){kv_join} "
                f"ORDER BY {kv_order} {order}"
            )
            return engine.fetch(sql, [*params, *kv_params])
        else:
            sql = (
                f"SELECT {col_str} FROM files_full AS m "
                f"JOIN ({path_sql}) AS s USING(path)"
            )
            return engine.fetch(sql, params)
