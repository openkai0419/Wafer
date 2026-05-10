from __future__ import annotations

from ...plugin import BaseFilterPlugin
from ...utils.profiling import profiler

from .registry import MarkRegistry
from .widget import MarkFilterWidget


class MarkFilter(BaseFilterPlugin):
    NAME = "mark"
    DISPLAY_NAME = "Mark"
    DEFAULT_ENABLED = True
    PRIORITY = 80

    @classmethod
    def create_widget(cls, parent=None):
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
        ids = params.get("mark_ids") or []
        if not ids:
            return None, []
        mode = (params.get("mode") or "OR").upper()
        keys = [MarkRegistry.key(str(mark_id)) for mark_id in ids]
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
