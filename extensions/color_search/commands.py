from __future__ import annotations

from wafer.plugin import ActionKit, MenuGroup, require

from ._color import normalize_hex, normalize_tolerance


@require(w="MainWindow")
def apply_color_filter(ctx, w, hex_color: str = "", tolerance: float = 0.1, mode: str = "append_or", join: str = "OR"):
    hex_color = normalize_hex(hex_color)
    if not hex_color:
        return
    bar = {
        "filter": "color",
        "params": {"colors": [{"hex": hex_color, "tolerance": normalize_tolerance(tolerance), "enabled": True}], "mode": str(join or "OR").upper()},
        "op": "AND" if str(mode).lower() == "append_and" else "OR",
        "enabled": True,
    }
    w.search_row_widget.apply_bars([bar], mode="append")
    w.sync_service_from_ui()
    w.search_service.execute_if_auto()


@require(w="MainWindow")
def apply_selected_color(ctx, w, hex_color: str = ""):
    hex_color = normalize_hex(hex_color)
    if not hex_color:
        return
    widget = w.search_row_widget.selected_param_widget("color")
    if widget is None or not widget.replace_selected_color(hex_color):
        return
    w.sync_service_from_ui()
    w.search_service.execute_if_auto()


class ColorSearchCommands(MenuGroup):
    NAME = "Color"
    PRIORITY = 1000
    SCOPE = "viewer"
    DEFAULT_ENABLED = True

    @classmethod
    def commands(cls):
        return [
            ActionKit.Command(
                path="color_search.apply_filter",
                display="Apply Color Filter",
                hidden=True,
                params=[
                    ActionKit.Param(name="hex_color", value=""),
                    ActionKit.Param(name="tolerance", value=0.1, min_value=0.0, max_value=1.0),
                    ActionKit.Param(name="mode", value=["append_or", "append_and"]),
                    ActionKit.Param(name="join", value=["OR", "AND"]),
                ],
                func=apply_color_filter,
            ),
            ActionKit.Command(
                path="color_search.apply_selected_color",
                display="Apply Selected Color",
                hidden=True,
                params=[ActionKit.Param(name="hex_color", value="")],
                func=apply_selected_color,
            ),
        ]
