from PySide6 import QtWidgets, QtCore, QtGui, QtWebEngineWidgets
from ...common import get_main_based_directory, uipx
from ...profiling import init_env
logger, profiler = init_env()

class OverlayLoadingIndicator(QtWidgets.QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        self.setAttribute(QtCore.Qt.WA_NoSystemBackground)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint)

        self.make_spinner()

        self.hide()
        self._parent = parent
        parent.installEventFilter(self)
    
    def make_spinner(self):
        self.spinner = QtWebEngineWidgets.QWebEngineView()
        self.spinner.page().setBackgroundColor(QtCore.Qt.transparent)

        html_path = get_main_based_directory() / "resources/Dual Ring@1x-1.0s-300px-300px.html"
        self.spinner.load(html_path.resolve().as_uri())
        self.spinner.setFixedSize(uipx(120), uipx(120))

        self.spinner.setParent(self)
        self.spinner.move(uipx(8), uipx(8))  # 左上に余白つきで表示

    def start(self):
        self.resize(self._parent.size())
        self.move(0, 0)
        self.show()
        self.raise_()

    def stop(self):
        self.hide()

    def eventFilter(self, watched, event):
        if watched == self._parent and event.type() == QtCore.QEvent.Resize:
            self.resize(self._parent.size())
        return super().eventFilter(watched, event)
