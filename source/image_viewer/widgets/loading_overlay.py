from PySide6 import QtWidgets, QtCore, QtGui
from ...profiling import init_env
logger, profiler = init_env()

class OverlayLoadingIndicator(QtWidgets.QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        self.setAttribute(QtCore.Qt.WA_NoSystemBackground)
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)

        self.spinner = QtWidgets.QLabel("読み込み中...", self)
        self.spinner.setAlignment(QtCore.Qt.AlignCenter)
        self.spinner.setStyleSheet(
            "color: white; font-size: 20px; background-color: rgba(0, 0, 0, 160); "
            "padding: 20px; border-radius: 10px;"
        )

        layout = QtWidgets.QVBoxLayout(self)
        layout.addStretch()
        layout.addWidget(self.spinner, alignment=QtCore.Qt.AlignCenter)
        layout.addStretch()

        self.hide()
        self._parent = parent
        parent.installEventFilter(self)

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