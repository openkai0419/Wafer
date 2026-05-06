from __future__ import annotations

from pathlib import Path

from ..constants import VIRTUAL_PATH_SEPARATOR
from ..core.db.db_utils import build_like_condition, escape_like
from ..core.db.query import SYSTEM_FILE_HASH_KEY, STANDARD_KEYS, standard_key_columns
from ..plugin.query.base import BaseFilterPlugin
from ..utils.profiling import profiler


def _normalize_text_inputs(params):
    keys = params.get("keys") or []
    if isinstance(keys, str):
        keys = [keys]
    else:
        keys = list(keys)
    keywords = params.get("keywords")
    separator = params.get("keyword_separator")
    if isinstance(keywords, str):
        keywords = [w.strip() for w in keywords.split(separator)] if separator else [keywords]
    elif isinstance(keywords, (list, tuple)):
        keywords = list(keywords)
    include = [kw for kw in (keywords or []) if kw and not kw.startswith("-")]
    exclude = [kw[1:] for kw in (keywords or []) if kw and kw.startswith("-") and len(kw) > 1]
    return keys, include, exclude


def _kv_part(from_clause, key_col, val_col, path_expr, other_keys, include_kw, keyword_mode, query_mode, exclude_keys=()):
    conds, params = [], []
    if other_keys:
        conds.append(f"{key_col} IN ({','.join('?' for _ in other_keys)})")
        params.extend(other_keys)
    if exclude_keys:
        conds.append(f"{key_col} NOT IN ({','.join('?' for _ in exclude_keys)})")
        params.extend(exclude_keys)
    if include_kw:
        c, v = build_like_condition(val_col, include_kw, keyword_mode, query_mode)
        conds.append(f"({c})")
        params.extend(v)
    w = f"WHERE {' AND '.join(conds)}" if conds else ""
    return f"SELECT {path_expr} FROM {from_clause} {w}", params


def _file_hash_part(include_kw, keyword_mode, query_mode):
    conds, params = [], []
    if include_kw:
        c, v = build_like_condition("s.file_hash", include_kw, keyword_mode, query_mode)
        conds.append(f"({c})")
        params.extend(v)
    w = f"WHERE {' AND '.join(conds)}" if conds else ""
    return f"SELECT i.path FROM sources AS s JOIN files AS i ON i.source = s.source {w}", params


def _standard_part(key, include_kw, keyword_mode, query_mode):
    cols = standard_key_columns(key)
    if cols is None:
        return None, []
    from_clause, path_col, val_col = cols
    conds, params = [], []
    if include_kw:
        c, v = build_like_condition(val_col, include_kw, keyword_mode, query_mode)
        conds.append(f"({c})")
        params.extend(v)
    w = f"WHERE {' AND '.join(conds)}" if conds else ""
    return f"SELECT {path_col} AS path FROM {from_clause} {w}", params


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
        return {k: params[k] for k in ("keys", "query_mode", "keyword_mode", "keyword_separator") if k in params}

    @classmethod
    @profiler.profile
    def build_path_query(cls, params, normalize_path):
        keys, include_kw, exclude_kw = _normalize_text_inputs(params)
        query_mode = params.get("query_mode", "LIKE")
        keyword_mode = params.get("keyword_mode", "OR")
        require_keys = params.get("require_keys", True)

        if require_keys and not keys:
            return "SELECT path FROM files WHERE 0", []

        query_all = not keys
        non_std_keys = [k for k in keys if k != SYSTEM_FILE_HASH_KEY and k not in STANDARD_KEYS]
        std_keys = [k for k in keys if k in STANDARD_KEYS] if not query_all else list(STANDARD_KEYS)
        parts, all_params = [], []

        if query_all or non_std_keys:
            sql, p = _kv_part(
                "meta_info AS mi",
                'mi."key"',
                'mi."value"',
                "mi.path",
                non_std_keys if not query_all else [],
                include_kw,
                keyword_mode,
                query_mode,
                (SYSTEM_FILE_HASH_KEY,) if query_all else (),
            )
            parts.append(sql)
            all_params.extend(p)

            sql, p = _kv_part(
                "tags AS t JOIN sources AS s ON s.file_hash = t.file_hash JOIN files AS i ON i.source = s.source",
                't."key"',
                't."value"',
                "i.path",
                non_std_keys if not query_all else [],
                include_kw,
                keyword_mode,
                query_mode,
            )
            parts.append(sql)
            all_params.extend(p)

        for k in std_keys:
            sql, p = _standard_part(k, include_kw, keyword_mode, query_mode)
            if sql is not None:
                parts.append(sql)
                all_params.extend(p)

        if query_all or SYSTEM_FILE_HASH_KEY in keys:
            sql, p = _file_hash_part(include_kw, keyword_mode, query_mode)
            parts.append(sql)
            all_params.extend(p)

        if not parts:
            return None, []

        subquery = " UNION ALL ".join(parts)

        if exclude_kw:
            exc_sql, exc_params = cls._build_exclude(keys if not query_all else [], query_all, exclude_kw, query_mode)
            if exc_sql:
                subquery = f"SELECT sq.path FROM ({subquery}) AS sq WHERE sq.path NOT IN ({exc_sql})"
                all_params.extend(exc_params)

        return f"SELECT DISTINCT path FROM ({subquery})", all_params

    @classmethod
    def _build_exclude(cls, keys, query_all, exclude_kw, query_mode):
        parts, params = [], []
        non_std_keys = [k for k in keys if k != SYSTEM_FILE_HASH_KEY and k not in STANDARD_KEYS]
        std_keys = [k for k in keys if k in STANDARD_KEYS] if not query_all else list(STANDARD_KEYS)
        if query_all or non_std_keys:
            conds, p = [], []
            if non_std_keys:
                conds.append(f'em."key" IN ({",".join("?" for _ in non_std_keys)})')
                p.extend(non_std_keys)
            elif query_all:
                conds.append('em."key" <> ?')
                p.append(SYSTEM_FILE_HASH_KEY)
            c, v = build_like_condition('em."value"', exclude_kw, "OR", query_mode)
            conds.append(f"({c})")
            p.extend(v)
            parts.append(f"SELECT em.path FROM meta_info AS em WHERE {' AND '.join(conds)}")
            params.extend(p)

            conds2, p2 = [], []
            if non_std_keys:
                conds2.append(f'et."key" IN ({",".join("?" for _ in non_std_keys)})')
                p2.extend(non_std_keys)
            c2, v2 = build_like_condition('et."value"', exclude_kw, "OR", query_mode)
            conds2.append(f"({c2})")
            p2.extend(v2)
            parts.append(f"SELECT ei.path FROM tags AS et JOIN sources AS es ON es.file_hash = et.file_hash JOIN files AS ei ON ei.source = es.source WHERE {' AND '.join(conds2)}")
            params.extend(p2)

        for k in std_keys:
            cols = standard_key_columns(k)
            if cols is None:
                continue
            from_clause, path_col, val_col = cols
            c, v = build_like_condition(val_col, exclude_kw, "OR", query_mode)
            parts.append(f"SELECT {path_col} AS path FROM {from_clause} WHERE ({c})")
            params.extend(v)

        if query_all or SYSTEM_FILE_HASH_KEY in keys:
            c3, p3 = build_like_condition("es.file_hash", exclude_kw, "OR", query_mode)
            parts.append(f"SELECT ei.path FROM sources AS es JOIN files AS ei ON ei.source = es.source WHERE ({c3})")
            params.extend(p3)
        if not parts:
            return "", []
        return " UNION ".join(parts), params


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
            nd = normalize_path(str(Path(d).resolve()))
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


class MarkFilter(BaseFilterPlugin):
    NAME = "mark"
    DISPLAY_NAME = "Mark"
    PRIORITY = 80

    @classmethod
    def create_widget(cls, parent=None):
        from .mark.widget import MarkFilterWidget

        return MarkFilterWidget(parent)

    @classmethod
    def read_params(cls, widget):
        return widget.read_params()

    @classmethod
    def write_params(cls, widget, params):
        widget.write_params(params)

    @classmethod
    def inheritable_params(cls, params):
        return {k: params[k] for k in ("mode",) if k in params}

    @classmethod
    @profiler.profile
    def build_path_query(cls, params, normalize_path):
        from .mark.registry import MarkRegistry

        ids = params.get("mark_ids") or []
        if not ids:
            return None, []
        mode = (params.get("mode") or "OR").upper()
        keys = [MarkRegistry.key(str(mid)) for mid in ids]
        placeholders = ",".join(["?"] * len(keys))
        base = (
            f"SELECT mi.path, mi.key AS k FROM meta_info AS mi WHERE mi.key IN ({placeholders}) "
            f"UNION ALL "
            f"SELECT i.path, t.key AS k FROM tags AS t "
            f"JOIN sources AS s ON s.file_hash = t.file_hash "
            f"JOIN files AS i ON i.source = s.source "
            f"WHERE t.key IN ({placeholders})"
        )
        base_params = list(keys) + list(keys)
        if mode == "AND" and len(keys) > 1:
            sql = f"SELECT path FROM ({base}) GROUP BY path HAVING COUNT(DISTINCT k) >= ?"
            return sql, base_params + [len(keys)]
        return f"SELECT DISTINCT path FROM ({base})", base_params
