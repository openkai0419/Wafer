from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtWidgets
from wafer.utils.formatting import dpix
from wafer.core.actions.bridge import ActionKit, Menu, Settings, UI

from . import menu_demo, drag_demo
for clss in [*menu_demo.get_menu_classes(), *drag_demo.get_menu_classes()]:
    clss.register()


class DemoButton(QtWidgets.QPushButton, ActionKit.UIMixin):
    def __init__(self, name: str, parent=None):
        super().__init__(name, parent)
        self.init_command_binding(name, enable_drops=True, use_existing_events=True)

    def extend_context(self, *args, **kwargs):
        return {"button": self.binding_scope()}

class DemoPane(QtWidgets.QFrame, ActionKit.UIMixin):
    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.setMinimumSize(dpix(240), dpix(160))
        self.init_command_binding(name, enable_drops=True)
        self._header = QtWidgets.QLabel(name, self)
        self._header.setAlignment(QtCore.Qt.AlignCenter)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        l = QtWidgets.QVBoxLayout(self)
        l.addWidget(self._header, 1)

    def extend_context(self, *args, **kwargs):
        return {"pane": self.binding_scope(), "header": self._header.text(), "test": "True"}

class TestLineEdit(QtWidgets.QLineEdit):
    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.setPlaceholderText(f"Type here in {name}...")

class MainWindow(QtWidgets.QMainWindow, ActionKit.UIMixin):
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

        self.line = UI.set_block_parent(TestLineEdit("LineEdit 1", self))
        c.addWidget(self.line, 0)
        self.line2 = UI.set_block_parent(TestLineEdit("LineEdit 2", self))
        c.addWidget(self.line2, 0)
        self._setup_menu_bar()  


    def _setup_menu_bar(self):
        mb = self.menuBar()
        m = Menu.session(self).from_folder("binding").build()
        m.setTitle("Binding")
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
    

    w = MainWindow()
    w.resize(dpix(640), dpix(400))
    w.show()
    
    Settings.configure(
        mouse_bindings=str(base / "mouse_bindings.json"),
        key_bindings=str(base / "key_bindings.json"),
        command_options=str(base / ".command_options.json"),
    )

    Settings.activate()
    


def main():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    bootstrap()
    app.exec()


if __name__ == "__main__":
    main()
