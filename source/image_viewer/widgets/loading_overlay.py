from PySide6 import QtCore, QtWebEngineWidgets, QtWidgets
from ...common.funcs import get_resource_path, uipx


class OverlayLoadingIndicator(QtWidgets.QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        self.setAttribute(QtCore.Qt.WA_NoSystemBackground)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint)
        self._make_spinner()
        self.hide()

    def _make_spinner(self):
        self.spinner = QtWebEngineWidgets.QWebEngineView()
        self.spinner.page().setBackgroundColor(QtCore.Qt.transparent)
        html_path = get_resource_path() / 'Ring_Load_spinner.html'
        self.spinner.load(html_path.resolve().as_uri())
        size = uipx(52)
        self.spinner.setFixedSize(size, size)
        self.spinner.setParent(self)
        self.spinner.move(0, 0)
        self.setFixedSize(size, size)

    def start(self):
        self.show()

    def stop(self):
        self.hide()
