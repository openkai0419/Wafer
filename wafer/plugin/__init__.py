from .registry import BasePlugin, PluginRegistry
from .viewer.base import BaseViewerPlugin, ImageViewerPlugin, WidgetViewerPlugin
from .grid.base import BaseGridPlugin, ImageGridPlugin, WidgetGridPlugin
from .collector.base import BaseCollectorPlugin, CollectorResult
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
