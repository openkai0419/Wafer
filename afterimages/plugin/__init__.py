from .registry import BasePlugin, PluginRegistry
from .viewer.base import BaseViewerPlugin
from .grid.base import BaseGridPlugin
from .collector.base import BaseCollectorPlugin, CollectorResult
from afterimages.utils.logs import AppLogger
from afterimages.utils.profiling import profiler
from afterimages.core.actions.bridge import ActionKit
from afterimages.core.qt.rate_limit import QtDebounceManager as _QtDebounceManager

qt_debounce_manager = _QtDebounceManager()


def load_thumbnail(path: str, size=None):
    from .grid.handler import grid_resolver
    return grid_resolver.load(path, size)

CommandMeta = ActionKit.Command
CommandParam = ActionKit.Param
MenuGroup = ActionKit.MenuBase
DragMenuGroup = ActionKit.DragMenuBase
