from __future__ import annotations

from pathlib import Path

from ..core.db.db_utils import build_like_condition, escape_like
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


def _kv_part(from_clause, key_col, val_col, path_expr, other_keys, include_kw, keyword_mode, query_mode):
    conds, params = [], []
    if other_keys:
        conds.append(f"{key_col} IN ({','.join('?' for _ in other_keys)})")
        params.extend(other_keys)
    if include_kw:
        c, v = build_like_condition(val_col, include_kw, keyword_mode, query_mode)
        conds.append(f"({c})")
        params.extend(v)
    w = f"WHERE {' AND '.join(conds)}" if conds else ""
    return f"SELECT {path_expr} FROM {from_clause} {w}", params


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
    def bind_key_store(cls, widget, key_store):
        prev = getattr(widget, "_bound_key_store", None)
        if prev is not None:
            prev.updated.disconnect(widget.keys_combo.remake)
        widget._bound_key_store = key_store
        key_store.updated.connect(widget.keys_combo.remake)
        if key_store.data:
            widget.keys_combo.remake(key_store.data)

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
        parts, all_params = [], []

        sql, p = _kv_part(
            "meta_info AS mi",
            'mi."key"',
            'mi."value"',
            "mi.path",
            keys if not query_all else [],
            include_kw,
            keyword_mode,
            query_mode,
        )
        parts.append(sql)
        all_params.extend(p)

        sql, p = _kv_part(
            "tags AS t JOIN sources AS s ON s.file_hash = t.file_hash JOIN files AS i ON i.source = s.source",
            't."key"',
            't."value"',
            "i.path",
            keys if not query_all else [],
            include_kw,
            keyword_mode,
            query_mode,
        )
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
        conds, p = [], []
        if keys:
            conds.append(f'em."key" IN ({",".join("?" for _ in keys)})')
            p.extend(keys)
        c, v = build_like_condition('em."value"', exclude_kw, "OR", query_mode)
        conds.append(f"({c})")
        p.extend(v)
        parts.append(f"SELECT em.path FROM meta_info AS em WHERE {' AND '.join(conds)}")
        params.extend(p)
        conds2, p2 = [], []
        if keys:
            conds2.append(f'et."key" IN ({",".join("?" for _ in keys)})')
            p2.extend(keys)
        c2, v2 = build_like_condition('et."value"', exclude_kw, "OR", query_mode)
        conds2.append(f"({c2})")
        p2.extend(v2)
        parts.append(f"SELECT ei.path FROM tags AS et JOIN sources AS es ON es.file_hash = et.file_hash JOIN files AS ei ON ei.source = es.source WHERE {' AND '.join(conds2)}")
        params.extend(p2)
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
        keys = [MarkRegistry.tag_key(str(mid)) for mid in ids]
        placeholders = ",".join(["?"] * len(keys))
        base = f"SELECT i.path FROM tags t JOIN sources s ON s.file_hash = t.file_hash JOIN files i ON i.source = s.source WHERE t.key IN ({placeholders})"
        if mode == "AND" and len(keys) > 1:
            sql = (
                "SELECT path FROM ("
                "SELECT i.path AS path, t.key AS k FROM tags t "
                "JOIN sources s ON s.file_hash = t.file_hash "
                "JOIN files i ON i.source = s.source "
                f"WHERE t.key IN ({placeholders})"
                ") GROUP BY path HAVING COUNT(DISTINCT k) >= ?"
            )
            return sql, list(keys) + [len(keys)]
        return f"SELECT DISTINCT path FROM ({base})", list(keys)
