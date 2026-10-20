from ...core.common.paths import get_resource_path


def get_icon():
    from PySide6 import QtGui

    return QtGui.QIcon(str(get_resource_path() / "icon.ico"))
