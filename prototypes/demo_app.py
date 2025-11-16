from PySide6 import QtCore, QtWidgets
from .command.ui import MenuBuilder
from .menu_demo import *
from .binding.mixins import CommandBindingMixin
from .binding.manager import BindingManager
from .binding.mouse.defaults import default_mouse_bindings
from .binding.key.defaults import default_key_bindings


class DemoPane(QtWidgets.QFrame, CommandBindingMixin):
    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.setMinimumSize(240, 160)
        self.init_command_binding(name)
        self._header = QtWidgets.QLabel(name, self)
        self._header.setAlignment(QtCore.Qt.AlignCenter)
        l = QtWidgets.QVBoxLayout(self)
        l.addWidget(self._header, 1)

    def provider(self, *args,**kwargs):
        return {"scope": self.binding_scope()}

class TestLineEdit(QtWidgets.QLineEdit):
    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.setPlaceholderText(f"Type here in {name}...")
        self.setFocusPolicy(QtCore.Qt.NoFocus)

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Prototype Command Test")
        cw = QtWidgets.QWidget(self)
        c = QtWidgets.QVBoxLayout(cw)
        l = QtWidgets.QHBoxLayout(cw)
        c.addLayout(l)
        self.pane1 = DemoPane("Widget A", cw)
        self.pane2 = DemoPane("Widget B", cw)
        self.pane3 = DemoPane("Widget C", cw)
        l.addWidget(self.pane1, 1)
        l.addWidget(self.pane2, 1)
        l.addWidget(self.pane3, 1)
        self.setCentralWidget(cw)

        self.line = TestLineEdit("LineEdit 1", self)
        c.addWidget(self.line, 0)
        self.line2 = TestLineEdit("LineEdit 2", self)
        c.addWidget(self.line2, 0)
        BindingManager.activate(defaults=default_mouse_bindings(), key_defaults=default_key_bindings())
        self._setup_menu_bar()

    def _setup_menu_bar(self):
        mb = self.menuBar()
        builder = MenuBuilder(self)
        m = builder.use("binding")
        mb.addMenu(m)


def main():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w = MainWindow()
    w.resize(640, 400)
    w.show()
    app.exec()


if __name__ == "__main__":
    main()
