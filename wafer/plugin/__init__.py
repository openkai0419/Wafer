from importlib import import_module

_EXPORTS = {
    "MultiWidgetViewerPlugin": (".viewer.base", None),
    "ViewerContext": (".viewer.base", None),
    "WidgetViewerPlugin": (".viewer.base", None),
    "viewer_context_values": (".viewer.base", None),
    "BaseGridPlugin": (".grid.base", None),
    "WidgetGridPlugin": (".grid.base", None),
    "BaseBadgeOverlayPlugin": (".grid_overlay.base", None),
    "BaseCellOverlayPlugin": (".grid_overlay.base", None),
    "BaseOverlayPlugin": (".grid_overlay.base", None),
    "GridOverlayCell": (".grid_overlay.base", None),
    "GridOverlayContext": (".grid_overlay.base", None),
    "OverlayBadge": (".grid_overlay.base", None),
    "OverlayHelper": (".grid_overlay.helper", None),
    "BaseCollectorPlugin": (".collector.base", None),
    "BaseSingletonCollector": (".collector.base", None),
    "CollectorResult": (".collector.base", None),
    "BaseParserPlugin": (".parser.base", None),
    "BaseSingletonParser": (".parser.base", None),
    "ParserResult": (".parser.base", None),
    "BaseFilterPlugin": (".query.base", None),
    "BaseSortPlugin": (".query.base", None),
    "BaseLayoutPlugin": (".layout.base", None),
    "BasePanelPlugin": (".panel.base", None),
    "PluginConfig": (".config", None),
    "KeyFilter": (".key_filter", None),
    "MODE_BLACKLIST": (".key_filter", None),
    "MODE_WHITELIST": (".key_filter", None),
    "BaseKeyValuePanelPlugin": (".key_value_panel.base", None),
    "BaseRenameSourcePlugin": (".rename.base", None),
    "SegmentInfo": (".rename.base", None),
    "BaseImageLoader": (".imageloader.base", None),
    "ActionKit": ("..qt.commands.bridge", None),
    "require": ("..qt.commands.command.require", None),
    "require_v": ("..qt.commands.command.require", None),
    "CommandMeta": ("..qt.commands.bridge", "ActionKit.Command"),
    "CommandParam": ("..qt.commands.bridge", "ActionKit.Param"),
    "MenuGroup": ("..qt.commands.bridge", "ActionKit.MenuBase"),
    "DragMenuGroup": ("..qt.commands.bridge", "ActionKit.DragMenuBase"),
}


def __getattr__(name):
    entry = _EXPORTS.get(name)
    if entry is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_path, attr_path = entry
    module = import_module(module_path, __name__)
    value = module
    for part in (attr_path or name).split("."):
        value = getattr(value, part)
    globals()[name] = value
    return value


def __dir__():
    return sorted(_EXPORTS)
