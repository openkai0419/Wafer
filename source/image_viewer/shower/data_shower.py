from PySide6 import QtCore, QtGui, QtWidgets

class SowerWidget(QtWidgets.QWidget):
    def __init__( self, parent= None):
        super().__init__(parent)

        self._layout = QtWidgets.QVBoxLayout(self)
        self._layout.setContentsMargins(12, 12, 12, 12)
        self._layout.setSpacing(0)
        self._layout.addStretch(1)
