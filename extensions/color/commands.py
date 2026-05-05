from __future__ import annotations

from wafer.core.commands.binding.instance_registry import InstanceRegistry

from ._color import normalize_hex, normalize_tolerance


def _color_widgets(search_row_widget) -> list:
    if search_row_widget is None or not hasattr(search_row_widget, "param_widgets"):
        return []
    return [widget for widget in search_row_widget.param_widgets("color") if widget is not None]


def _has_color(widget, hex_color: str) -> bool:
    if not hasattr(widget, "read_params"):
        return False
    params = widget.read_params()
    if not isinstance(params, dict):
        return False
    for color in params.get("colors") or []:
        if not isinstance(color, dict):
            continue
        if normalize_hex(str(color.get("hex") or "")) == hex_color:
            return True
    return False


def _search_container(search_row_widget=None):
    if search_row_widget is not None:
        return search_row_widget
    return InstanceRegistry.instance().get_one("SearchContainer")


def apply_color_filter(search_row_widget=None, hex_color: str = "", tolerance: float = 0.1, mode: str = "append_or", join: str = "OR"):
    search_row_widget = _search_container(search_row_widget)
    if search_row_widget is None:
        return
    hex_color = normalize_hex(hex_color)
    if not hex_color:
        return
    for widget in _color_widgets(search_row_widget):
        if _has_color(widget, hex_color):
            return
    tolerance = normalize_tolerance(tolerance)
    for widget in reversed(_color_widgets(search_row_widget)):
        if not hasattr(widget, "add_color"):
            continue
        widget.add_color(hex_color, tolerance)
        return
    bar = {
        "filter": "color",
        "params": {"colors": [{"hex": hex_color, "tolerance": tolerance, "enabled": True}], "mode": "OR"},
        "enabled": True,
    }
    search_row_widget.apply_bars([bar], mode="append")


def apply_selected_color(search_row_widget=None, hex_color: str = ""):
    search_row_widget = _search_container(search_row_widget)
    if search_row_widget is None:
        return
    hex_color = normalize_hex(hex_color)
    if not hex_color:
        return
    for widget in reversed(_color_widgets(search_row_widget)):
        if not hasattr(widget, "has_selection") or not widget.has_selection():
            continue
        if not hasattr(widget, "replace_selected_color") or not widget.replace_selected_color(hex_color):
            return
        return
