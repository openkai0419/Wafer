from __future__ import annotations

from wafer.plugin import CommandMeta, CommandParam, MenuGroup, require
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
    m.refresh()


@require(m="MappingWidget")
def relayout_selection(ctx, m):
    m.relayout_selection()


@require(m="MappingWidget")
def toggle_space_mode(ctx, m):
    m.set_space_mode("live" if m.effective_mode() == "space" else "space")


def _space_mode_checked() -> bool:
    from .widget import MappingWidget

    widget = MappingWidget.instance()
    return bool(widget is not None and widget.effective_mode() == "space")


@require(m="MappingWidget")
def toggle_labels(ctx, m):
    m.set_labels_shown(not m.labels_shown)


def _labels_checked() -> bool:
    from .widget import MappingWidget

    widget = MappingWidget.instance()
    return bool(widget is not None and widget.labels_shown)


@require(m="MappingWidget")
def image_scale_up(ctx, m, ratio: float = 1.1):
    m.image_scale_up(float(ratio))


@require(m="MappingWidget")
def image_scale_down(ctx, m, ratio: float = 1.1):
    m.image_scale_down(float(ratio))


@require(m="MappingWidget")
def toggle_selection_mode(ctx, m):
    m.set_selection_mode("single" if m.selection_mode == "group" else "group")


def _group_mode_checked() -> bool:
    from .widget import MappingWidget

    widget = MappingWidget.instance()
    return bool(widget is not None and widget.selection_mode == "group")


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
            CommandMeta(path="mapping.relayout_selection", display="Relayout Selection", func=relayout_selection),
            CommandMeta(path="mapping.recompute", display="Recompute", func=recompute),
            CommandMeta(path="mapping.space_mode", display="Use Precomputed Space", func=toggle_space_mode, checked=_space_mode_checked),
            CommandMeta(path="mapping.toggle_labels", display="Show Labels", func=toggle_labels, checked=_labels_checked),
            CommandMeta(path="mapping.image_scale_up", display="Larger Images", func=image_scale_up, params=[CommandParam(name="ratio", value=1.1, min_value=1.01, max_value=4.0)]),
            CommandMeta(path="mapping.image_scale_down", display="Smaller Images", func=image_scale_down, params=[CommandParam(name="ratio", value=1.1, min_value=1.01, max_value=4.0)]),
            CommandMeta(path="mapping.selection_mode", display="Select Whole Groups", func=toggle_selection_mode, checked=_group_mode_checked),
        ]
