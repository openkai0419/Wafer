from __future__ import annotations

from functools import partial

from ..constants import VIRTUAL_PATH_SEPARATOR
from ..core.db.db_utils import build_like_condition
from ..core.db.query import ALL_PATHS_SQL, key_path_queries, parse_keywords, path_prefix_condition
from ..plugin.query.base import BaseFilterPlugin
from ..core.profiling import profiler


def _normalize_text_inputs(params):
    keys = params.get("keys") or []
    if isinstance(keys, str):
        keys = [keys]
    else:
        keys = list(keys)
    include, exclude = parse_keywords(
        params.get("keywords"),
        params.get("keyword_separator"),
        params.get("trim_keywords", True),
    )
    return keys, include, exclude


def _keyword_conditions(column, keywords, keyword_mode, query_mode):
    if not keywords:
        return [], []
    condition, params = build_like_condition(column, keywords, keyword_mode, query_mode)
    return [f"({condition})"], params


class TextFilter(BaseFilterPlugin):
    NAME = "text"
    DISPLAY_NAME = "Text"
    PRIORITY = 100

    @classmethod
    def create_widget(cls, parent=None):
        from ..plugin.query.widgets import TextFilterWidget

        return TextFilterWidget(parent)

    @classmethod
    def read_params(cls, widget):
        return widget.read_params()

    @classmethod
    def write_params(cls, widget, params):
        widget.write_params(params)

    @classmethod
    def inheritable_params(cls, params):
        return {k: params[k] for k in ("keys", "query_mode", "keyword_mode", "keyword_separator", "trim_keywords") if k in params}

    @classmethod
    @profiler.profile
    def build_path_query(cls, params, normalize_path):
        keys, include_kw, exclude_kw = _normalize_text_inputs(params)
        query_mode = params.get("query_mode", "LIKE")
        keyword_mode = params.get("keyword_mode", "OR")
        require_keys = params.get("require_keys", True)

        if require_keys and not keys:
            return "SELECT path FROM files WHERE 0", []

        parts, all_params = key_path_queries(keys, partial(_keyword_conditions, keywords=include_kw, keyword_mode=keyword_mode, query_mode=query_mode))
        if not parts:
            return None, []
        if parts == [ALL_PATHS_SQL] and not exclude_kw:
            return ALL_PATHS_SQL, []

        subquery = " UNION ALL ".join(parts)

        if exclude_kw:
            exc_parts, exc_params = key_path_queries(keys, partial(_keyword_conditions, keywords=exclude_kw, keyword_mode="OR", query_mode=query_mode))
            subquery = f"SELECT sq.path FROM ({subquery}) AS sq WHERE sq.path NOT IN ({' UNION '.join(exc_parts)})"
            all_params.extend(exc_params)

        return f"SELECT DISTINCT path FROM ({subquery})", all_params


class DirectoryFilter(BaseFilterPlugin):
    NAME = "directory"
    PRIORITY = 90
    QUERY_SCOPE = "global"

    @classmethod
    @profiler.profile
    def build_path_query(cls, params, normalize_path):
        condition, bind = cls.build_path_condition(params, normalize_path)
        if condition is None:
            return None, []
        return f"SELECT path FROM files WHERE {condition}", bind

    @classmethod
    @profiler.profile
    def build_path_condition(cls, params, normalize_path, column="path"):
        directories = params.get("directories")
        if not directories:
            return None, []
        include_subfolders = params.get("include_subfolders", True)
        clauses, bind = [], []
        for d in directories:
            if not isinstance(d, str) or not d:
                continue
            prefix = normalize_path(d) + "/"
            clause, clause_bind = path_prefix_condition(column, prefix)
            if not include_subfolders:
                clause = f"({clause} AND instr(substr({column}, ?), '/') = 0)"
                clause_bind.append(len(prefix) + 1)
            clauses.append(clause)
            bind.extend(clause_bind)
        if not clauses:
            return None, []
        return f"({' OR '.join(clauses)})", bind


class ContainedFilesFilter(BaseFilterPlugin):
    NAME = "contained_files"
    DISPLAY_NAME = "Contained Files"
    PRIORITY = 89
    QUERY_SCOPE = "global"
    INTERNAL_FILTER = True

    @classmethod
    @profiler.profile
    def build_path_query(cls, params, normalize_path):
        if params.get("include", True):
            return None, []
        return "SELECT path FROM files WHERE source_extension IS NULL", []


class SourceChildrenFilter(BaseFilterPlugin):
    NAME = "source_children"
    PRIORITY = 88
    INTERNAL_FILTER = True

    @classmethod
    @profiler.profile
    def build_path_query(cls, params, normalize_path):
        source = params.get("source")
        if not isinstance(source, str) or not source:
            return None, []
        normalized = normalize_path(source)
        condition, bind = path_prefix_condition("path", f"{normalized}{VIRTUAL_PATH_SEPARATOR}")
        return f"SELECT path FROM files WHERE source = ? AND {condition}", [normalized, *bind]
