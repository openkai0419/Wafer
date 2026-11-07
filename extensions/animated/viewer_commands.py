from PySide6 import QtWidgets

from wafer.core.lang.manager import t
from wafer.core.store.settings import app_settings
from wafer.plugin import MenuGroup, MenuPath, CommandMeta, require
from wafer.qt.commands.binding.instance_registry import InstanceRegistry

from ._common import apply_cache_limit
from .settings import CACHE_LIMIT_DEFAULT_MB, CACHE_LIMIT_KEY

_MINIMUM_MB = 64
_MAXIMUM_MB = 1024 * 1024
_STEP_MB = 256


def _avw():
    return InstanceRegistry.instance().get_one("AnimatedViewerWidget")


@require(vw="AnimatedViewerWidget")
def toggle_fit_mode(ctx, vw):
    vw.toggle_fit_mode()


def set_cache_limit(ctx):
    value, ok = QtWidgets.QInputDialog.getInt(
        ctx.get("widget") or None,
        t("Animated Cache Limit"),
        t("Limit in MiB, applied to the Grid and the Viewer separately in each Viewer window:"),
        app_settings.get(CACHE_LIMIT_KEY, CACHE_LIMIT_DEFAULT_MB, int),
        _MINIMUM_MB,
        _MAXIMUM_MB,
        _STEP_MB,
    )
    if not ok:
        return
    app_settings.save_immediate(CACHE_LIMIT_KEY, value)
    apply_cache_limit(value)


class AnimatedViewerCommands(MenuGroup):
    NAME = f"{MenuPath.WIDGETS}/Animated"
    PRIORITY = 1200
    DEFAULT_ENABLED = True

    @classmethod
    def commands(cls):
        return [
            ":Animated Viewer",
            CommandMeta(
                path="aview.toggle_fit_mode",
                display="Contain/Cover",
                func=toggle_fit_mode,
                checked=lambda: getattr(_avw(), "cover_mode", False),
            ),
            CommandMeta(path="aview.cache_limit", display="Cache Limit...", func=set_cache_limit),
        ]
