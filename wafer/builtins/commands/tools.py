import os
from functools import partial
from PySide6 import QtWidgets, QtCore, QtGui
from ...qt.commands.bridge import ActionKit
from ...utils.formatting import dpix
from ...utils.paths import get_resource_path, get_app_root_dir
from ..._version import __version__
from ...core.lang.manager import t
from .panel import open_panel


def show_about(ctx):
    import sys
    from PySide6 import __version__ as qt_version

    w = ctx.get_instance("MainWindow")
    parent = w if w else None
    lines = [
        "<h2>Wafer</h2>",
        f"<p>Version: <b>{__version__}</b></p>",
        f"<p>Python: {sys.version.split()[0]}<br>Qt: {QtCore.qVersion()}<br>PySide6: {qt_version}</p>",
    ]
    msg = QtWidgets.QMessageBox(parent)
    msg.setWindowTitle(t("About Wafer"))
    msg.setTextFormat(QtCore.Qt.RichText)
    msg.setText("".join(lines))
    msg.setStandardButtons(QtWidgets.QMessageBox.Ok)
    icon = QtGui.QIcon(str(get_resource_path() / "icon.ico"))
    if not icon.isNull():
        msg.setIconPixmap(icon.pixmap(dpix(64), dpix(64)))
    msg.exec()


def show_readme(ctx):
    from ...qt.widgets.markdown_browser import MarkdownBrowser
    from ...qt.layout.standalone import open_standalone

    readme_path = os.path.join(str(get_app_root_dir()), "README.md")
    if not os.path.isfile(readme_path):
        return

    def factory():
        browser = MarkdownBrowser()
        browser.load_file(readme_path)
        return browser

    open_standalone(factory, "README.md", "readme_viewer", size=(dpix(700), dpix(800)), parent=ctx.get_instance("MainWindow"))


class ToolCommands(ActionKit.MenuBase):
    NAME = "Setting"
    PRIORITY = 95
    SCOPE = "*"

    @classmethod
    def commands(cls):
        return [
            ":Manager",
            ActionKit.Command(
                path="setting.plugin_manager",
                display="Plugin Manager",
                func=partial(open_panel, name="Plugin Manager"),
            ),
            ActionKit.Command(
                path="setting.database_manager",
                display="Database Manager",
                func=partial(open_panel, name="Database Manager"),
            ),
            ActionKit.Command(
                path="setting.metadata_filter",
                display="Metadata Filter",
                func=partial(open_panel, name="Metadata Filter"),
            ),
            ":Tools",
            ActionKit.Command(
                path="setting.batch_renamer",
                display="Batch Renamer",
                func=partial(open_panel, name="Batch Renamer"),
            ),
        ]


class HelpCommands(ActionKit.MenuBase):
    NAME = "Setting"
    PRIORITY = 97
    SCOPE = "*"

    @classmethod
    def commands(cls):
        return [
            ":Help",
            ActionKit.Command(
                path="help.readme",
                display="README.md",
                func=show_readme,
            ),
            ActionKit.Command(
                path="help.about",
                display="Version Info",
                func=show_about,
            ),
        ]
