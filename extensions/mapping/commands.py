from __future__ import annotations

from wafer.plugin import CommandMeta, CommandParam, MenuGroup, MenuPath, require
from wafer.qt.common.notifier import Notifier

PANEL_NAME = "Mapping"


def ctx_paths(ctx) -> list[str]:
    paths = ctx.get("paths")
    if isinstance(paths, list) and paths:
        return list(dict.fromkeys(str(path) for path in paths if path))
    path = ctx.get("path")
    return [str(path)] if path else []


def _panel(window):
    from .panel import MappingPanel

    widget = window._layout_manager.panel_widget(PANEL_NAME)
    return widget if isinstance(widget, MappingPanel) else None


def _open(ctx, window, apply):
    paths = ctx_paths(ctx)
    if not paths:
        Notifier.info("No files selected")
        return
    panel = _panel(window)
    if panel is None:
        return
    apply(panel.map_tab, paths)
    panel.show_map()
    window._layout_manager.ensure_panel_visible(PANEL_NAME)


@require(w="MainWindow")
def mapping_set(ctx, w):
    _open(ctx, w, lambda widget, paths: widget.set_files(paths, w.database_path))


@require(w="MainWindow")
def mapping_add(ctx, w):
    _open(ctx, w, lambda widget, paths: widget.add_files(paths, w.database_path))


@require(w="MainWindow")
def mapping_remove(ctx, w):
    paths = ctx_paths(ctx)
    panel = _panel(w)
    if panel is not None and paths:
        panel.map_tab.remove_files(paths)


def map_panel(ctx):
    panel = ctx.get("map_panel")
    if panel is not None:
        return panel
    from .panel import MappingPanel

    mapping = MappingPanel.instance()
    return None if mapping is None else mapping.current_map()


def select_all(ctx):
    panel = map_panel(ctx)
    if panel is not None:
        panel.select_all()


def mapping_panel(ctx):
    from .widget import MappingWidget

    panel = map_panel(ctx)
    return panel if isinstance(panel, MappingWidget) else None


def drill_down(ctx):
    panel = mapping_panel(ctx)
    if panel is not None:
        panel.drill_down()


def drill_up(ctx):
    panel = mapping_panel(ctx)
    if panel is not None:
        panel.drill_up()


def frame_selection(ctx):
    panel = map_panel(ctx)
    if panel is not None:
        panel.map_view.frame_selection()


def recompute(ctx):
    panel = map_panel(ctx)
    if panel is not None:
        panel.refresh()


def current_tab(ctx=None):
    panel = map_panel(ctx or {})
    return None if panel is None else panel.tab


def toggle_thumbnails(ctx):
    tab = current_tab(ctx)
    if tab is not None:
        tab.set_thumbnails_shown(not tab.thumbnails_shown)


def _thumbnails_checked() -> bool:
    tab = current_tab()
    return tab is not None and tab.thumbnails_shown


def image_scale_up(ctx, ratio: float = 1.1):
    tab = current_tab(ctx)
    if tab is not None:
        tab.set_image_scale(tab.image_scale * float(ratio))


def image_scale_down(ctx, ratio: float = 1.1):
    tab = current_tab(ctx)
    if tab is not None:
        tab.set_image_scale(tab.image_scale / float(ratio))


def toggle_selection_mode(ctx):
    tab = current_tab(ctx)
    if tab is not None:
        tab.set_selection_mode("single" if tab.selection_mode == "group" else "group")


def _group_mode_checked() -> bool:
    tab = current_tab()
    return tab is not None and tab.selection_mode == "group"


class MappingGridCommands(MenuGroup):
    NAME = MenuPath.SELECTION
    PRIORITY = 1000
    DEFAULT_ENABLED = True

    @classmethod
    def commands(cls):
        return [
            "Mapping/:Mapping",
            CommandMeta(path="Mapping/mapping.add", display="Add", func=mapping_add),
            CommandMeta(path="Mapping/mapping.set", display="Set", func=mapping_set),
            CommandMeta(path="Mapping/mapping.remove", display="Remove", func=mapping_remove),
        ]


class MappingViewCommands(MenuGroup):
    NAME = f"{MenuPath.WIDGETS}/{PANEL_NAME}"
    PRIORITY = 1001
    DEFAULT_ENABLED = True

    @classmethod
    def commands(cls):
        return [
            ":Mapping",
            CommandMeta(path="mapping.select_all", display="Select All", func=select_all),
            CommandMeta(path="mapping.frame_selection", display="Frame Selection", func=frame_selection),
            CommandMeta(path="mapping.drill_down", display="Map Selection Only", func=drill_down),
            CommandMeta(path="mapping.drill_up", display="Back", func=drill_up),
            CommandMeta(path="mapping.recompute", display="Recompute", func=recompute),
            CommandMeta(path="mapping.toggle_thumbnails", display="Show Thumbnails", func=toggle_thumbnails, checked=_thumbnails_checked),
            CommandMeta(path="mapping.image_scale_up", display="Larger Images", func=image_scale_up, params=[CommandParam(name="ratio", value=1.1, min_value=1.01, max_value=4.0)]),
            CommandMeta(path="mapping.image_scale_down", display="Smaller Images", func=image_scale_down, params=[CommandParam(name="ratio", value=1.1, min_value=1.01, max_value=4.0)]),
            CommandMeta(path="mapping.selection_mode", display="Select Whole Groups", func=toggle_selection_mode, checked=_group_mode_checked),
        ]
