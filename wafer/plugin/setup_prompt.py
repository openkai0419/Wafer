import os

from ..utils.logs import AppLogger
from .settings import _ini_path, PluginSettings
from .loader import get_plugin_dir
from .installer import needs_setup


def plugin_setup_needed() -> bool:
    if not os.path.isfile(_ini_path()):
        return True
    plugin_dir = get_plugin_dir()
    missing = [f for f in PluginSettings().active_folders() if os.path.isdir(os.path.join(plugin_dir, f)) and needs_setup(os.path.join(plugin_dir, f))]
    if missing:
        AppLogger.warning(f"Enabled plugins need setup: {missing}. Opening Plugin Manager to install.")
        return True
    return False
