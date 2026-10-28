from __future__ import annotations

from functools import partial

from ..constants import VIRTUAL_PATH_SEPARATOR
from ..core.db.db_utils import build_like_condition, escape_like
from ..core.db.query import SYSTEM_FILE_HASH_KEY, STANDARD_KEYS, key_value_path_query, parse_keywords, standard_key_path_query, where_clause
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


def _file_hash_part(value_conditions):
    conds, params = value_conditions("s.file_hash")
    return f"SELECT i.path FROM sources AS s JOIN files AS i ON i.source = s.source{where_clause(conds)}", params


def _key_parts(keys, value_conditions):
    query_all = not keys
    non_std_keys = [k for k in keys if k != SYSTEM_FILE_HASH_KEY and k not in STANDARD_KEYS]
    std_keys = [k for k in keys if k in STANDARD_KEYS] if not query_all else list(STANDARD_KEYS)
    queries = []
    if query_all or non_std_keys:
        queries.append(key_value_path_query("meta_info", value_conditions, keys=non_std_keys, exclude_keys=(SYSTEM_FILE_HASH_KEY,) if query_all else ()))
        queries.append(key_value_path_query("tags", value_conditions, keys=non_std_keys))
    queries.extend(standard_key_path_query(k, value_conditions) for k in std_keys)
    if query_all or SYSTEM_FILE_HASH_KEY in keys:
        queries.append(_file_hash_part(value_conditions))
    queries = [(sql, params) for sql, params in queries if sql is not None]
    return [sql for sql, _ in queries], [p for _, params in queries for p in params]


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

        parts, all_params = _key_parts(keys, partial(_keyword_conditions, keywords=include_kw, keyword_mode=keyword_mode, query_mode=query_mode))
        if not parts:
            return None, []

        subquery = " UNION ALL ".join(parts)

        if exclude_kw:
            exc_parts, exc_params = _key_parts(keys, partial(_keyword_conditions, keywords=exclude_kw, keyword_mode="OR", query_mode=query_mode))
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
        directories = params.get("directories")
        if not directories:
            return None, []
        include_subfolders = params.get("include_subfolders", True)
        clauses, bind = [], []
        for d in directories:
            if not isinstance(d, str) or not d:
                continue
            nd = normalize_path(d)
            prefix = (nd + "/") if nd else ""
            esc_p = escape_like(prefix)
            if not include_subfolders:
                clauses.append("(path LIKE ? ESCAPE '\\' AND path NOT LIKE ? ESCAPE '\\')")
                bind.extend([f"{esc_p}%", f"{esc_p}%/%"])
            else:
                clauses.append("path LIKE ? ESCAPE '\\'")
                bind.append(f"{esc_p}%")
        if not clauses:
            return None, []
        where = " OR ".join(clauses)
        return f"SELECT DISTINCT path FROM files WHERE {where}", bind


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
        prefix = f"{normalized}{VIRTUAL_PATH_SEPARATOR}"
        return "SELECT path FROM files WHERE source = ? AND path LIKE ? ESCAPE '\\'", [normalized, f"{escape_like(prefix)}%"]
