from turtle import st
from PySide6 import QtCore, QtGui

from ...actions.bridge import Command, Kit

def test(ctx):
    path = ctx.get("path")
    if not path:
        return
    print(path)

class GraphicsViewCommands(Kit.MenuBase):
    prefix = "GraphicsView"

    COMMAND_DEFS = [
        Kit.Command(path="gv.test", display="Test", func=test),]

    def create_definitions(self):
        return self.COMMAND_DEFS