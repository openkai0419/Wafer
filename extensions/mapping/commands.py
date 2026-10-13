from __future__ import annotations

from wafer.plugin import CommandMeta, MenuGroup, require
from wafer.qt.common.notifier import Notifier

PANEL_NAME = "Mapping"


def ctx_paths(ctx) -> list[str]:
    paths = ctx.get("paths")
    if isinstance(paths, list) and paths:
        return list(dict.fromkeys(str(path) for path in paths if path))
    path = ctx.get("path")
    return [str(path)] if path else []


def _panel(window):
    from .widget import MappingWidget

    widget = window._layout_manager.panel_widget(PANEL_NAME)
    return widget if isinstance(widget, MappingWidget) else None


def _open(ctx, window, apply):
    paths = ctx_paths(ctx)
    if not paths:
        Notifier.info("No files selected")
        return
    widget = _panel(window)
    if widget is None:
        return
    apply(widget, paths)
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
    widget = _panel(w)
    if widget is not None and paths:
        widget.remove_files(paths)


@require(m="MappingWidget")
def select_all(ctx, m):
    m.select_all()


@require(m="MappingWidget")
def drill_down(ctx, m):
    m.drill_down()


@require(m="MappingWidget")
def drill_up(ctx, m):
    m.drill_up()


@require(m="MappingWidget")
def recompute(ctx, m):
    m.recompute()


@require(m="MappingWidget")
def toggle_grouping(ctx, m):
    m.set_grouping(not m.grouping)


def _grouping_checked() -> bool:
    from .widget import MappingWidget

    widget = MappingWidget.instance()
    return bool(widget is not None and widget.grouping)


class MappingGridCommands(MenuGroup):
    NAME = "Mapping"
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
    NAME = "Mapping View"
    PRIORITY = 1001
    DEFAULT_ENABLED = True

    @classmethod
    def commands(cls):
        return [
            ":Mapping",
            CommandMeta(path="mapping.select_all", display="Select All", func=select_all),
            CommandMeta(path="mapping.drill_down", display="Map Selection Only", func=drill_down),
            CommandMeta(path="mapping.drill_up", display="Back", func=drill_up),
            CommandMeta(path="mapping.recompute", display="Recompute", func=recompute),
            CommandMeta(path="mapping.toggle_grouping", display="Show Groups", func=toggle_grouping, checked=_grouping_checked),
        ]
