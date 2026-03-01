from PySide6 import QtCore, QtGui, QtWidgets
from afterimages.utils.formatting import dpix

class OverlayLoadingIndicator(QtWidgets.QWidget):

    _INTERVAL_MS = 16
    _SPIN_DURATION_MS = 1000
    _ARC_SPAN = 256

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        self.setAttribute(QtCore.Qt.WA_NoSystemBackground)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint)
        size = dpix(52)
        self.setFixedSize(size, size)
        self._angle = 0.0
        self._step = 360.0 * self._INTERVAL_MS / self._SPIN_DURATION_MS
        self._bg_color = QtGui.QColor(60, 60, 60, 153)
        self._arc_pen = QtGui.QPen(QtGui.QColor(0xDF, 0xDF, 0xDF), dpix(4.0), QtCore.Qt.SolidLine, QtCore.Qt.RoundCap)
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(self._INTERVAL_MS)
        self._timer.timeout.connect(self._tick)
        self.hide()

    def _tick(self):
        self._angle = (self._angle - self._step) % 360.0
        self.update()

    def start(self):
        self.show()
        self._timer.start()

    def stop(self):
        self._timer.stop()
        self.hide()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        r = self.rect()
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(self._bg_color)
        radius = dpix(10)
        painter.drawRoundedRect(r, radius, radius)
        margin = dpix(10)
        arc_rect = QtCore.QRectF(r).adjusted(margin, margin, -margin, -margin)
        painter.setPen(self._arc_pen)
        painter.setBrush(QtCore.Qt.NoBrush)
        start = int(self._angle * 16)
        span = int(self._ARC_SPAN * 16)
        painter.drawArc(arc_rect, start, span)
        painter.end()
