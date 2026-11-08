from PySide6 import QtWidgets

from wafer.core.lang.manager import t
from wafer.plugin import CommandMeta, MenuGroup, MenuPath

from .settings import zip_config

_MINIMUM_GB = 1
_MAXIMUM_GB = 1024


def set_cache_limit(ctx):
    value, ok = QtWidgets.QInputDialog.getInt(
        ctx.get("widget") or None,
        t("Zip Cache Limit"),
        t("Disk space in GiB for files extracted from archives:"),
        zip_config.load()["cache_limit_gb"],
        _MINIMUM_GB,
        _MAXIMUM_GB,
    )
    if ok:
        zip_config.save(cache_limit_gb=value)


class ZipCommands(MenuGroup):
    NAME = f"{MenuPath.WIDGETS}/Zip"
    PRIORITY = 1300
    DEFAULT_ENABLED = True

    @classmethod
    def commands(cls):
        return [
            ":Zip",
            CommandMeta(path="zip.cache_limit", display="Cache Limit...", func=set_cache_limit),
        ]
