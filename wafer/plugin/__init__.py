from .registry import PluginBase, BasePlugin, PluginRegistry
from .viewer.base import BaseViewerPlugin, ImageViewerPlugin, WidgetViewerPlugin
from .grid.base import BaseGridPlugin, ImageGridPlugin, WidgetGridPlugin
from .collector.base import BaseCollector, BaseCollectorPlugin, BaseSingletonCollector, CollectorResult
from .query.base import BaseFilterPlugin, BaseSortPlugin
from .layout.base import BaseLayoutPlugin
from .rename.base import BaseRenameSourcePlugin, SegmentInfo
from ..core.commands.bridge import ActionKit
from ..core.commands.command.require import require, require_v
from ..core.qt.rate_limit import QtDebounceManager as _QtDebounceManager

qt_debounce_manager = _QtDebounceManager()


def load_thumbnail(path: str, size=None):
    from .grid.handler import grid_resolver
    return grid_resolver.load(path, size)

CommandMeta = ActionKit.Command
CommandParam = ActionKit.Param
MenuGroup = ActionKit.MenuBase
DragMenuGroup = ActionKit.DragMenuBase
