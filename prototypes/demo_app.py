from PySide6 import QtCore, QtWidgets
from source.common.profiling import profiler
from source.common.funcs import uipx
from .command.ui import MenuBuilder
from .menu_demo import *
from .drag_demo import * 
from .binding.mixins import CommandBindingMixin
from .binding.manager import BindingManager
from .defaults import default_mouse_bindings, default_key_bindings

class DemoButton(QtWidgets.QPushButton, CommandBindingMixin):
    def __init__(self, name: str, parent=None):
        super().__init__(name, parent)
        self.init_command_binding(name, enable_drops=True)

    def extend_context(self, ctx, cmd=None, event=None, key=None, source=None):
        return {"button": self.binding_scope()}

class DemoPane(QtWidgets.QFrame, CommandBindingMixin):
    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.setMinimumSize(uipx(240), uipx(160))
        self.init_command_binding(name, enable_drops=True)
        self._header = QtWidgets.QLabel(name, self)
        self._header.setAlignment(QtCore.Qt.AlignCenter)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        l = QtWidgets.QVBoxLayout(self)
        l.addWidget(self._header, 1)

    def extend_context(self, ctx, cmd=None, event=None, key=None, source=None):
        return {"pane": self.binding_scope(), "header": self._header.text(), "test": "True"}

class TestLineEdit(QtWidgets.QLineEdit):
    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.setPlaceholderText(f"Type here in {name}...")

class MainWindow(QtWidgets.QMainWindow, CommandBindingMixin):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Prototype Command Test")
        self.setFocusPolicy(QtCore.Qt.ClickFocus)
        self.init_command_binding("Test Window", enable_drops=True)
        cw = QtWidgets.QWidget(self)
        c = QtWidgets.QVBoxLayout(cw)
        l = QtWidgets.QHBoxLayout(cw)
        c.addLayout(l)
        self.pane1 = DemoPane("Widget A", cw)
        self.pane2 = DemoButton("Widget B", cw)
        self.pane3 = DemoButton("Widget C", cw)
        l.addWidget(self.pane1, 1)
        l.addWidget(self.pane2, 1)
        l.addWidget(self.pane3, 1)
        
        self.drag_demo = DemoPane("Drag Demo Widget", cw)
        c.addWidget(self.drag_demo, 1)
        
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

    def closeEvent(self, event):
        from .command.state import CommandOptionStore, ActionGroupStateManager
        try:
            ActionGroupStateManager().commit()
            CommandOptionStore().commit()
        except Exception as e:
            print(f"Failed to save settings: {e}")
        super().closeEvent(event)

def add_focus_style(app):
    def on_focus_changed(old, new):
        if old is not None:
            old.setProperty("focusHighlight", False)
            old.style().unpolish(old)
            old.style().polish(old)
        if new is not None:
            new.setProperty("focusHighlight", True)
            new.style().unpolish(new)
            new.style().polish(new)

    app.focusChanged.connect(on_focus_changed)
    app.setStyleSheet(
        """
        *[focusHighlight="true"] {
            border: 2px solid #ffaa00;
        }
        """
    )
    return app



def main():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    # add_focus_style(app)

    w = MainWindow()
    w.resize(uipx(640), uipx(400))
    w.show()
    app.exec()


if __name__ == "__main__":
    main()
