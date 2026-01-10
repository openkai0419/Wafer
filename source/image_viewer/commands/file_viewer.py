from PySide6 import QtCore, QtGui, QtWidgets

from ...actions.bridge import Kit


class FileViewerCommands(Kit.MenuBase):
    prefix = "FileViewer"

    commands = [
        ":FileViewer",
        Kit.Command(path="fv.next_file", display="Next File", func=lambda: None),
        "-",
    ]
