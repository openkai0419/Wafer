from PySide6 import QtWidgets

from ...core.commands.bridge import ActionKit, UI
from ...plugin.grid.handler import grid_resolver, VIEWER_THUMBNAIL_DEFAULT_SIZE
from ...utils.paths import resolve_data_path
from ...core.platform.folders import show_in_explorer
from ...core.setting.app_settings import app_settings

_SETTING_KEY = "viewer/thumbnail_default_size"

_PRESET_SIZES = [256, 512, 1024, 2048, 4096]


def _restore_thumbnail_size():
    size = app_settings.get(_SETTING_KEY, VIEWER_THUMBNAIL_DEFAULT_SIZE, value_type=int)
    grid_resolver.thumbnail_size = size


def set_viewer_thumbnail_default_size(ctx):
    widget = ctx.get("widget") or None
    current = grid_resolver.thumbnail_size
    items = [str(s) for s in _PRESET_SIZES]
    current_text = str(current)
    current_index = items.index(current_text) if current_text in items else 0
    value, ok = QtWidgets.QInputDialog.getItem(
        widget,
        "Default Size of the Windows thumbnail in file viewer",
        f"Select thumbnail size (current: {current}px):",
        items,
        current_index,
        editable=True,
    )
    if not ok or not value:
        return
    try:
        size = int(value)
    except ValueError:
        return
    size = max(64, min(size, 16384))
    grid_resolver.thumbnail_size = size
    app_settings.save_immediate(_SETTING_KEY, size)


class SettingCommands(ActionKit.MenuBase):
    NAME = "Setting"
    PRIORITY = 90

    @classmethod
    def commands(cls):
        return [
            ":Setting",
            ActionKit.Command(
                path="setting.viewer_thumbnail_default_size",
                display="Viewer Thumbnail Default Size",
                func=set_viewer_thumbnail_default_size,
            ),
            "-",
            ":Binding",
            ActionKit.Command(
                path="setting.keybind",
                display="Key Binding Window",
                func=lambda ctx: UI.open_shortcut_binding_editor(parent=ctx.get("widget") or None),
            ),
            ActionKit.Command(
                path="setting.mousebind",
                display="Mouse Binding Window",
                func=lambda ctx: UI.open_mouse_binding_editor(parent=ctx.get("widget") or None),
            ),
            ActionKit.Command(
                path="setting.openbindingfolder",
                display="Open Binding Files in Explorer",
                func=lambda ctx: show_in_explorer(str(resolve_data_path("binding/")), show_first_if_folder=True),
            ),
        ]
