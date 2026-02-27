from PySide6 import QtWidgets

from ...actions.bridge import Kit
from ...plugin_core.grid.handler import grid_handler, VIEWER_THUMBNAIL_DEFAULT_SIZE
from ..viewer_settings import main_setting

_SETTING_KEY = 'viewer/thumbnail_default_size'

_PRESET_SIZES = [256, 512, 1024, 2048, 4096]


def _restore_viewer_thumbnail_size():
    size = main_setting.get(_SETTING_KEY, VIEWER_THUMBNAIL_DEFAULT_SIZE, value_type=int)
    grid_handler.viewer_thumbnail_size = size


def set_viewer_thumbnail_default_size(ctx):
    widget = ctx.get("widget") or None
    current = grid_handler.viewer_thumbnail_size
    items = [str(s) for s in _PRESET_SIZES]
    current_text = str(current) if current in _PRESET_SIZES else str(current)
    current_index = items.index(current_text) if current_text in items else 0
    value, ok = QtWidgets.QInputDialog.getItem(
        widget, "Default Size of the Windows thumbnail in file viewer",
        f"Select thumbnail size (current: {current}px):",
        items, current_index, editable=True,
    )
    if not ok or not value:
        return
    try:
        size = int(value)
    except ValueError:
        return
    size = max(64, min(size, 16384))
    grid_handler.viewer_thumbnail_size = size
    main_setting.save_important(_SETTING_KEY, size)


class SettingCommands(Kit.MenuBase):
    NAME = "Setting"

    @classmethod
    def commands(cls):
        return [
            ":Setting",
            Kit.Command(
                path="setting.viewer_thumbnail_default_size",
                display="Viewer Thumbnail Default Size",
                func=set_viewer_thumbnail_default_size,
            ),
        ]
