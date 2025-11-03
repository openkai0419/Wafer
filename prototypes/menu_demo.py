from PySide6 import QtGui, QtWidgets
from .commandbase import MenuProviderBase, CommandMenuBuilder, CommandMeta, CommandParam, register_command_defs, RegistryBackedMenu
from datetime import datetime


class FileMenu(RegistryBackedMenu):
    DISPLAY = "File"
    def create_definitions(self):
        items = []
        for i in range(4):
            items.append({
                "meta": CommandMeta(id=f"file.{i}", display=f"file {i}"),
                "func": (lambda x=i: (lambda: print(f"file {x}")))()
            })
        return items

class PathMenu(RegistryBackedMenu):
    DISPLAY = "Path"
    def create_definitions(self):
        items = []
        for i in range(4):
            items.append({
                "meta": CommandMeta(id=f"path.{i}", display=f"path {i}"),
                "func": (lambda x=i: (lambda: print(f"path {x}")))()
            })
        return items

class CmdMenu(RegistryBackedMenu):
    DISPLAY = "Commands"

    def create_definitions(self):
        return [
            {
                "meta": CommandMeta(id="cmd.hello", display="Hello", params=[CommandParam(name="widget", type=str, default="", description="Widget")]),
                "func": lambda widget="": print(f"hello from {widget}")
            },
            {
                "meta": CommandMeta(id="cmd.time", display="Show Time"),
                "func": lambda: print(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            },
            "---",
            ":Options",
            {
                "meta": CommandMeta(id="cmd.echo", display="Echo", params=[CommandParam(name="text", type=str, default="echo")], has_options=True),
                "func": lambda text="echo": print(text)
            },
            {
                "meta": CommandMeta(id="cmd.count", display="Count", params=[CommandParam(name="value", type=int, default=1, description="Value")], has_options=True),
                "func": lambda value=1: print(f"count {value}")
            },
            "---",
            ":Toggle",
            {
                "meta": CommandMeta(id="cmd.toggleVerbose", display="Verbose Mode", checkable=True, default_checked=False,
                                     params=[CommandParam(name="checked", type=bool, default=False)]),
                "func": lambda checked=False: print("verbose on" if checked else "verbose off")
            },
        ]

class AllMenu(MenuProviderBase):
    def __init__(self):
        self.file_menu = FileMenu()
        self.path_menu = PathMenu()
        self.cmd_menu = CmdMenu()

    def build_menu(self, parent: QtWidgets.QWidget) -> QtWidgets.QMenu:
        m = QtWidgets.QMenu(parent)
        m.addMenu(self.cmd_menu.build_submenu(parent))
        m.addMenu(self.path_menu.build_submenu(parent))
        m.addMenu(self.file_menu.build_submenu(parent))
        return m
