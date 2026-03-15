from __future__ import annotations

import re

from wafer.plugin.query.base import BaseFilterPlugin
from wafer.utils.profiling import profiler


def _escape_like(s):
    return s.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def _extract_literal_hints(pattern):
    try:
        re.compile(pattern)
    except re.error:
        return []

    runs = []
    current = []
    i = 0
    n = len(pattern)
    group_stack = []

    while i < n:
        c = pattern[i]

        if c == '\\' and i + 1 < n:
            nc = pattern[i + 1]
            if nc in 'dDwWsSbBAZG' or (nc.isdigit() and nc != '0'):
                _flush(current, runs)
                i += 2
                continue
            current.append(nc)
            i += 2
        elif c in '*+?':
            if c in '*?':
                if current:
                    current.pop()
            _flush(current, runs)
            i += 1
            if i < n and pattern[i] in '+?':
                i += 1
        elif c == '{':
            end = pattern.find('}', i)
            if end != -1:
                min_count = _parse_quantifier_min(pattern[i + 1:end])
                if min_count == 0 and current:
                    current.pop()
                _flush(current, runs)
                i = end + 1
            else:
                current.append(c)
                i += 1
        elif c == '[':
            _flush(current, runs)
            i = _skip_char_class(pattern, i + 1, n)
        elif c == '(':
            _flush(current, runs)
            group_stack.append((len(runs), False))
            i += 1
            i = _skip_group_modifier(pattern, i, n)
        elif c == ')':
            _flush(current, runs)
            if group_stack:
                start_idx, has_alt = group_stack.pop()
                if has_alt:
                    del runs[start_idx:]
            i += 1
        elif c == '|':
            _flush(current, runs)
            if group_stack:
                group_stack[-1] = (group_stack[-1][0], True)
            else:
                return []
            i += 1
        elif c in '.^$':
            _flush(current, runs)
            i += 1
        else:
            current.append(c)
            i += 1

    _flush(current, runs)
    return [r for r in runs if r]


def _flush(current, runs):
    if current:
        runs.append(''.join(current))
        current.clear()


def _parse_quantifier_min(text):
    try:
        parts = text.split(',')
        return int(parts[0]) if parts[0].strip() else 0
    except (ValueError, IndexError):
        return 0


def _skip_char_class(pattern, i, n):
    if i < n and pattern[i] in '^':
        i += 1
    if i < n and pattern[i] == ']':
        i += 1
    while i < n and pattern[i] != ']':
        if pattern[i] == '\\' and i + 1 < n:
            i += 2
        else:
            i += 1
    return i + 1 if i < n else i


def _skip_group_modifier(pattern, i, n):
    if i >= n or pattern[i] != '?':
        return i
    i += 1
    if i >= n:
        return i
    c = pattern[i]
    if c in ':=!':
        return i + 1
    if c == 'P':
        i += 1
        if i < n and pattern[i] == '<':
            end = pattern.find('>', i)
            return end + 1 if end != -1 else n
        if i < n and pattern[i] == '=':
            end = pattern.find(')', i)
            return end if end != -1 else n
        return i
    if c == '<':
        i += 1
        if i < n and pattern[i] in '=!':
            return i + 1
        end = pattern.find('>', i)
        return end + 1 if end != -1 else n
    return i


def _build_like_conditions(field, hints):
    if not hints:
        return [], []
    clauses = []
    params = []
    for h in hints:
        clauses.append(f"{field} LIKE ? ESCAPE '\\'")
        params.append(f'%{_escape_like(h)}%')
    return clauses, params


class RegexFilter(BaseFilterPlugin):
    NAME = 'regex'
    DISPLAY_NAME = 'Regex'
    PRIORITY = 95

    @classmethod
    def create_widget(cls, parent=None):
        from .widget import RegexFilterWidget
        return RegexFilterWidget(parent)

    @classmethod
    def read_params(cls, widget):
        return widget.read_params()

    @classmethod
    def write_params(cls, widget, params):
        widget.write_params(params)

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
        pattern = params.get('pattern', '')
        if not pattern:
            return None, []

        flags = re.IGNORECASE if params.get('ignore_case', False) else 0
        try:
            compiled = re.compile(pattern, flags)
        except re.error:
            return None, []

        params['_compiled'] = compiled

        keys, ignore_case = cls._normalize_params(params)
        require_keys = params.get('require_keys', True)
        if require_keys and not keys:
            return "SELECT path FROM files WHERE 0", []

        has_filepath = '__filepath__' in keys
        other_keys = [k for k in keys if k != '__filepath__']
        query_all = not keys
        hints = _extract_literal_hints(pattern)

        parts, all_params = [], []

        if has_filepath or query_all:
            conds, bind = _build_like_conditions('i.path', hints)
            w = f"WHERE {' AND '.join(conds)}" if conds else ""
            parts.append(f"SELECT i.path FROM files AS i {w}")
            all_params.extend(bind)

        if other_keys or query_all:
            sql, p = cls._kv_part(
                'meta_info AS mi', 'mi."key"', 'mi."value"', 'mi.path',
                other_keys, hints,
            )
            parts.append(sql)
            all_params.extend(p)

            sql, p = cls._kv_part(
                'tags AS t '
                'JOIN sources AS s ON s.file_hash = t.file_hash '
                'JOIN files AS i ON i.source = s.source',
                't."key"', 't."value"', 'i.path',
                other_keys, hints,
            )
            parts.append(sql)
            all_params.extend(p)

        if not parts:
            return None, []

        subquery = " UNION ALL ".join(parts)
        return f"SELECT DISTINCT path FROM ({subquery})", all_params

    @classmethod
    def _normalize_params(cls, params):
        keys = params.get('keys') or []
        if isinstance(keys, str):
            keys = [keys]
        else:
            keys = list(keys)
        ignore_case = params.get('ignore_case', False)
        return keys, ignore_case

    @classmethod
    def _kv_part(cls, from_clause, key_col, val_col, path_expr,
                 other_keys, hints):
        conds, params = [], []
        if other_keys:
            conds.append(f"{key_col} IN ({','.join('?' for _ in other_keys)})")
            params.extend(other_keys)
        val_conds, val_bind = _build_like_conditions(val_col, hints)
        conds.extend(val_conds)
        params.extend(val_bind)
        w = f"WHERE {' AND '.join(conds)}" if conds else ""
        return f"SELECT {path_expr} FROM {from_clause} {w}", params

    @classmethod
    def post_filter(cls, params, rows):
        compiled = params.get('_compiled')
        if compiled is None:
            return rows

        keys = params.get('keys') or []
        if isinstance(keys, str):
            keys = [keys]

        has_filepath = '__filepath__' in keys
        other_keys = [k for k in keys if k != '__filepath__']
        query_all = not keys

        if has_filepath and not other_keys and not query_all:
            return [r for r in rows if compiled.search(r['path'])]

        return rows
