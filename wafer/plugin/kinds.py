from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PluginKind:
    key: str
    label: str
    color: str


PLUGIN_KIND_VIEWER = "viewer"
PLUGIN_KIND_GRID = "grid"
PLUGIN_KIND_COLLECTOR = "collector"
PLUGIN_KIND_PARSER = "parser"
PLUGIN_KIND_FILTER = "filter"
PLUGIN_KIND_SORT = "sort"
PLUGIN_KIND_LAYOUT = "layout"
PLUGIN_KIND_PANEL = "panel"
PLUGIN_KIND_META_PANEL = "meta_panel"
PLUGIN_KIND_TAG_PANEL = "tag_panel"
PLUGIN_KIND_RENAME_SOURCE = "rename_source"
PLUGIN_KIND_IMAGE_LOADER = "imageloader"
PLUGIN_KIND_COMMAND = "command"

UNKNOWN_PLUGIN_KIND_COLOR = "#90a4ae"

PLUGIN_KINDS: dict[str, PluginKind] = {
    PLUGIN_KIND_PANEL: PluginKind(PLUGIN_KIND_PANEL, "Panel", "#FFAD4F"),
    PLUGIN_KIND_COMMAND: PluginKind(PLUGIN_KIND_COMMAND, "Command", "#FFF067"),

    PLUGIN_KIND_GRID: PluginKind(PLUGIN_KIND_GRID, "Grid", "#78BEFF"),
    PLUGIN_KIND_IMAGE_LOADER: PluginKind(PLUGIN_KIND_IMAGE_LOADER, "Loader", "#9DFFF2"),

    PLUGIN_KIND_VIEWER: PluginKind(PLUGIN_KIND_VIEWER, "Viewer", "#83FD83"),
    PLUGIN_KIND_META_PANEL: PluginKind(PLUGIN_KIND_META_PANEL, "Meta", "#C6FFBA"),
    PLUGIN_KIND_TAG_PANEL: PluginKind(PLUGIN_KIND_TAG_PANEL, "Tag", "#C6FFBA"),    
    
    PLUGIN_KIND_COLLECTOR: PluginKind(PLUGIN_KIND_COLLECTOR, "Collector", "#C99FFF"),
    PLUGIN_KIND_PARSER: PluginKind(PLUGIN_KIND_PARSER, "Parser", "#EC9FFF"),
    
    PLUGIN_KIND_FILTER: PluginKind(PLUGIN_KIND_FILTER, "Filter", "#E7B5B5"),
    PLUGIN_KIND_SORT: PluginKind(PLUGIN_KIND_SORT, "Sort", "#E0B3B3"),
    PLUGIN_KIND_LAYOUT: PluginKind(PLUGIN_KIND_LAYOUT, "Layout", "#DB8080"),
    PLUGIN_KIND_RENAME_SOURCE: PluginKind(PLUGIN_KIND_RENAME_SOURCE, "Rename", "#BDBDBD"),

}


ORDERABLE_PLUGIN_KIND_KEYS = (
    PLUGIN_KIND_GRID,
    PLUGIN_KIND_VIEWER,
    PLUGIN_KIND_FILTER,
    PLUGIN_KIND_SORT,
    PLUGIN_KIND_LAYOUT,
    PLUGIN_KIND_RENAME_SOURCE,
    PLUGIN_KIND_COMMAND,
)

PRIORITY_PLUGIN_KIND_KEYS = frozenset((PLUGIN_KIND_GRID, PLUGIN_KIND_VIEWER))


def plugin_kind_label(key: str) -> str:
    kind = PLUGIN_KINDS.get(key)
    if kind is not None:
        return kind.label
    return key.replace("_", " ").title()


def plugin_kind_color(key: str) -> str:
    kind = PLUGIN_KINDS.get(key)
    if kind is not None:
        return kind.color
    return UNKNOWN_PLUGIN_KIND_COLOR
