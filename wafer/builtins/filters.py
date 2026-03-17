from __future__ import annotations

from pathlib import Path

from ..plugin.query.base import BaseFilterPlugin
from ..utils.profiling import profiler


def _escape_like(s):
    return s.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def _match_clause(field, keywords, op, query_mode):
    if not keywords:
        return "", []
    if query_mode.upper() == "GLOB":
        clauses = [f"{field} GLOB ?" for _ in keywords]
        values = [f"*{kw}*" for kw in keywords]
    else:
        clauses = [f"{field} LIKE ? ESCAPE '\\'" for _ in keywords]
        values = [f"%{_escape_like(kw)}%" for kw in keywords]
    return f" {op} ".join(clauses), values


def _normalize_text_inputs(params):
    keys = params.get('keys') or []
    if isinstance(keys, str):
        keys = [keys]
    else:
        keys = list(keys)
    keywords = params.get('keywords')
    separator = params.get('keyword_separator')
    if isinstance(keywords, str):
        keywords = [w.strip() for w in keywords.split(separator)] if separator else [keywords]
    elif isinstance(keywords, (list, tuple)):
        keywords = list(keywords)
    include = [kw for kw in (keywords or []) if kw and not kw.startswith('-')]
    exclude = [kw[1:] for kw in (keywords or []) if kw and kw.startswith('-') and len(kw) > 1]
    return keys, include, exclude


def _kv_part(from_clause, key_col, val_col, path_expr,
             other_keys, include_kw, keyword_mode, query_mode):
    conds, params = [], []
    if other_keys:
        conds.append(f"{key_col} IN ({','.join('?' for _ in other_keys)})")
        params.extend(other_keys)
    if include_kw:
        c, v = _match_clause(val_col, include_kw, keyword_mode, query_mode)
        conds.append(f"({c})")
        params.extend(v)
    w = f"WHERE {' AND '.join(conds)}" if conds else ""
    return f"SELECT {path_expr} FROM {from_clause} {w}", params


class TextFilter(BaseFilterPlugin):
    NAME = 'text'
    DISPLAY_NAME = 'Text'
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
        return {k: params[k] for k in ('keys', 'query_mode', 'keyword_mode', 'keyword_separator') if k in params}

    @classmethod
    def bind_key_store(cls, widget, key_store):
        prev = getattr(widget, '_bound_key_store', None)
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
        query_mode = params.get('query_mode', 'LIKE')
        keyword_mode = params.get('keyword_mode', 'OR')
        require_keys = params.get('require_keys', True)

        if require_keys and not keys:
            return "SELECT path FROM files WHERE 0", []

        has_filepath = '__filepath__' in keys
        other_keys = [k for k in keys if k != '__filepath__']
        query_all = not keys
        parts, all_params = [], []

        if has_filepath or query_all:
            conds, bind = [], []
            if include_kw:
                c, v = _match_clause('i.path', include_kw, keyword_mode, query_mode)
                conds.append(f"({c})")
                bind.extend(v)
            w = f"WHERE {' AND '.join(conds)}" if conds else ""
            parts.append(f"SELECT i.path FROM files AS i {w}")
            all_params.extend(bind)

        if other_keys or query_all:
            sql, p = _kv_part(
                'meta_info AS mi', 'mi."key"', 'mi."value"', 'mi.path',
                other_keys, include_kw, keyword_mode, query_mode,
            )
            parts.append(sql)
            all_params.extend(p)

            sql, p = _kv_part(
                'tags AS t '
                'JOIN sources AS s ON s.file_hash = t.file_hash '
                'JOIN files AS i ON i.source = s.source',
                't."key"', 't."value"', 'i.path',
                other_keys, include_kw, keyword_mode, query_mode,
            )
            parts.append(sql)
            all_params.extend(p)

        if not parts:
            return None, []

        subquery = " UNION ALL ".join(parts)

        if exclude_kw:
            exc_sql, exc_params = cls._build_exclude(
                has_filepath, other_keys, query_all, exclude_kw, query_mode
            )
            if exc_sql:
                subquery = (
                    f"SELECT sq.path FROM ({subquery}) AS sq "
                    f"WHERE sq.path NOT IN ({exc_sql})"
                )
                all_params.extend(exc_params)

        return f"SELECT DISTINCT path FROM ({subquery})", all_params

    @classmethod
    def _build_exclude(cls, has_filepath, other_keys, query_all, exclude_kw, query_mode):
        parts, params = [], []
        if has_filepath or query_all:
            c, v = _match_clause('efi.path', exclude_kw, "OR", query_mode)
            parts.append(f"SELECT efi.path FROM files AS efi WHERE {c}")
            params.extend(v)
        if other_keys or query_all:
            conds, p = [], []
            if other_keys:
                conds.append(f"em.\"key\" IN ({','.join('?' for _ in other_keys)})")
                p.extend(other_keys)
            c, v = _match_clause('em."value"', exclude_kw, "OR", query_mode)
            conds.append(f"({c})")
            p.extend(v)
            parts.append(f"SELECT em.path FROM meta_info AS em WHERE {' AND '.join(conds)}")
            params.extend(p)
            conds2, p2 = [], []
            if other_keys:
                conds2.append(f"et.\"key\" IN ({','.join('?' for _ in other_keys)})")
                p2.extend(other_keys)
            c2, v2 = _match_clause('et."value"', exclude_kw, "OR", query_mode)
            conds2.append(f"({c2})")
            p2.extend(v2)
            parts.append(
                f"SELECT ei.path FROM tags AS et "
                f"JOIN sources AS es ON es.file_hash = et.file_hash "
                f"JOIN files AS ei ON ei.source = es.source "
                f"WHERE {' AND '.join(conds2)}"
            )
            params.extend(p2)
        if not parts:
            return "", []
        return " UNION ".join(parts), params


class DirectoryFilter(BaseFilterPlugin):
    NAME = 'directory'
    PRIORITY = 90
    SCOPE = 'global'

    @classmethod
    @profiler.profile
    def build_path_query(cls, params, normalize_path):
        directories = params.get('directories')
        if not directories:
            return None, []
        include_subfolders = params.get('include_subfolders', True)
        clauses, bind = [], []
        for d in directories:
            if not isinstance(d, str) or not d:
                continue
            nd = normalize_path(str(Path(d).resolve()))
            prefix = (nd + "/") if nd else ""
            esc_p = _escape_like(prefix)
            if not include_subfolders:
                clauses.append(
                    f"(path LIKE ? ESCAPE '\\' AND path NOT LIKE ? ESCAPE '\\')"
                )
                bind.extend([f"{esc_p}%", f"{esc_p}%/%"])
            else:
                clauses.append(f"path LIKE ? ESCAPE '\\'")
                bind.append(f"{esc_p}%")
        if not clauses:
            return None, []
        where = " OR ".join(clauses)
        return f"SELECT DISTINCT path FROM files WHERE {where}", bind
