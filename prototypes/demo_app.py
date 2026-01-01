from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtWidgets
from source.common.funcs import uipx
from .actions.facade import Classes, Settings, UI

class DemoButton(QtWidgets.QPushButton, Classes.UIMixin):
    def __init__(self, name: str, parent=None):
        super().__init__(name, parent)
        self.init_command_binding(name, enable_drops=True)

    def extend_context(self, ctx, cmd=None, event=None, key=None, source=None):
        return {"button": self.binding_scope()}

class DemoPane(QtWidgets.QFrame, Classes.UIMixin):
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

class MainWindow(QtWidgets.QMainWindow, Classes.UIMixin):
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
        self._setup_menu_bar()


    def _setup_menu_bar(self):
        mb = self.menuBar()
        builder = UI.get_builder(self)
        m = builder.use("binding")
        mb.addMenu(m)

    def closeEvent(self, event):
        try:
            Settings.commit()
        except Exception as e:
            print(f"Failed to save settings: {e}")
        super().closeEvent(event)

def bootstrap() -> None:
    root = Path(__file__).resolve().parent.parent
    base = root / ".temp" / "demo_app"
    
    Settings.configure(
        mouse_bindings=str(base / "mouse_bindings.json"),
        key_bindings=str(base / "key_bindings.json"),
        command_options=str(base / ".command_options.json"),
    )
    from . import menu_demo, drag_demo
    Settings.register_menus([*menu_demo.get_menu_classes(), *drag_demo.get_menu_classes()])

    w = MainWindow()
    w.resize(uipx(640), uipx(400))
    w.show()
    
    from .defaults import get_all_key_bindings, get_all_mouse_bindings
    Settings.activate(mouse_bindings=get_all_mouse_bindings(), key_bindings=get_all_key_bindings())
    


def main():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    bootstrap()
    app.exec()


if __name__ == "__main__":
    main()
