from __future__ import annotations

from wafer.plugin import BaseFilterPlugin
from wafer.utils.profiling import profiler

from ._color import color_param
from .settings import palette_keys


class ColorFilter(BaseFilterPlugin):
    NAME = "color"
    DISPLAY_NAME = "Color"
    PRIORITY = 85
    DEFAULT_ENABLED = True

    @classmethod
    def create_widget(cls, parent=None):
        from .widget import ColorFilterWidget

        return ColorFilterWidget(parent)

    @classmethod
    def read_params(cls, widget):
        return widget.read_params()

    @classmethod
    def write_params(cls, widget, params):
        widget.write_params(params)

    @classmethod
    def inheritable_params(cls, params):
        return {"mode": params.get("mode", "OR")}

    @classmethod
    @profiler.profile
    def build_path_query(cls, params, normalize_path):
        colors = [c for c in (color_param(item) for item in params.get("colors") or []) if c is not None]
        if not colors:
            return None, []
        parts = []
        bind = []
        for color in colors:
            sql, sql_params = _single_color_query(color)
            parts.append(sql)
            bind.extend(sql_params)
        mode = str(params.get("mode") or "OR").upper()
        op = " INTERSECT " if mode == "AND" and len(parts) > 1 else " UNION "
        return f"SELECT DISTINCT path FROM ({op.join(parts)})", bind


def _single_color_query(color: dict) -> tuple[str, list]:
    r, g, b = color["rgb"]
    keys = palette_keys()
    slot_sql = ",".join("?" for _ in keys)
    packed = "CAST(t.value_num AS INTEGER)"
    red = f"(({packed} / 65536) % 256)"
    green = f"(({packed} / 256) % 256)"
    blue = f"({packed} % 256)"
    distance = f"(({red} - ?) * ({red} - ?) + ({green} - ?) * ({green} - ?) + ({blue} - ?) * ({blue} - ?))"
    sql = (
        "SELECT DISTINCT i.path FROM tags AS t "
        "JOIN sources AS s ON s.file_hash = t.file_hash "
        "JOIN files AS i ON i.source = s.source "
        f"WHERE t.key IN ({slot_sql}) AND t.value_num IS NOT NULL AND {distance} <= ?"
    )
    return sql, [*tuple(f"color.{key}" for key in keys), r, r, g, g, b, b, color["radius_sq"]]
