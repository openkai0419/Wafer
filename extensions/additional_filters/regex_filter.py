from __future__ import annotations

import re
from functools import partial
from re import _constants as sre, _parser as re_parser

from wafer.core.db.db_utils import escape_like
from wafer.core.db.query import compiled_regex, key_path_queries
from wafer.plugin import BaseFilterPlugin
from wafer.core.profiling import profiler

_REPEATS = (sre.MAX_REPEAT, sre.MIN_REPEAT, sre.POSSESSIVE_REPEAT)


def _extract_literal_hints(pattern):
    try:
        parsed = re_parser.parse(pattern)
    except re.error:
        return []
    runs: list[str] = []
    current: list[str] = []
    _collect_runs(parsed, current, runs, ignore_case=False)
    _flush(current, runs)
    return runs


def _collect_runs(items, current, runs, *, ignore_case):
    for op, av in items:
        if op is sre.LITERAL and not (ignore_case and av > 127):
            current.append(chr(av))
        elif op is sre.SUBPATTERN:
            _group, add_flags, del_flags, body = av
            group_ignore_case = (ignore_case or bool(add_flags & re.IGNORECASE)) and not del_flags & re.IGNORECASE
            _collect_runs(body, current, runs, ignore_case=group_ignore_case)
        elif op is sre.ATOMIC_GROUP:
            _collect_runs(av, current, runs, ignore_case=ignore_case)
        elif op in _REPEATS and av[0] >= 1:
            _collect_runs(av[2], current, runs, ignore_case=ignore_case)
            _flush(current, runs)
        else:
            _flush(current, runs)


def _flush(current, runs):
    if current:
        runs.append("".join(current))
        current.clear()


def _build_value_conditions(field, hints, pattern):
    clauses = [f"{field} LIKE ? ESCAPE '\\'" for _ in hints]
    params = [f"%{escape_like(h)}%" for h in hints]
    return [*clauses, f"{field} REGEXP ?"], [*params, pattern]


class RegexFilter(BaseFilterPlugin):
    NAME = "regex"
    DISPLAY_NAME = "Regex"
    PRIORITY = 95
    DEFAULT_ENABLED = True

    @classmethod
    def create_widget(cls, parent=None):
        from .regex_widget import RegexFilterWidget

        return RegexFilterWidget(parent)

    @classmethod
    def read_params(cls, widget):
        return widget.read_params()

    @classmethod
    def write_params(cls, widget, params):
        widget.write_params(params)

    @classmethod
    def inheritable_params(cls, params):
        return {k: params[k] for k in ("keys", "ignore_case") if k in params}

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
        pattern = params.get("pattern", "")
        if not pattern:
            return None, []

        hints = _extract_literal_hints(pattern)
        if params.get("ignore_case", False):
            pattern = f"(?i){pattern}"
        try:
            compiled = compiled_regex(pattern)
        except re.error:
            return None, []

        keys = params.get("keys") or []
        if isinstance(keys, str):
            keys = [keys]
        if params.get("require_keys", True) and not keys:
            return "SELECT path FROM files WHERE 0", []

        if compiled.flags & re.IGNORECASE:
            hints = [h for h in hints if h.isascii()]
        parts, all_params = key_path_queries(list(keys), partial(_build_value_conditions, hints=hints, pattern=pattern))
        subquery = " UNION ALL ".join(parts)
        return f"SELECT DISTINCT path FROM ({subquery})", all_params
