from PySide6 import QtWidgets, QtCore, QtGui

from ...utils.formatting import dpix
from ..color.theme import ThemeManager


class InstallSplash(QtWidgets.QWidget):

    def __init__(self, title: str, icon: QtGui.QIcon = None,
                 message: str = 'Installing plugin dependencies.\nThis may take few minutes...'):
        super().__init__()
        self.setWindowTitle(title)
        w, h = dpix(360), dpix(80)
        self.setFixedSize(w, h)
        self.setWindowFlags(QtCore.Qt.Window | QtCore.Qt.FramelessWindowHint)
        p = ThemeManager.instance().palette
        self.setStyleSheet(f'background:{p.bg_secondary};')

        icon_size = dpix(48)
        margin = dpix(16)
        icon_label = QtWidgets.QLabel(self)
        if icon and not icon.isNull():
            icon_label.setPixmap(icon.pixmap(icon_size, icon_size))
        icon_label.setFixedSize(icon_size, icon_size)
        icon_label.setAlignment(QtCore.Qt.AlignCenter)
        icon_label.setGeometry(w - margin - icon_size, (h - icon_size) // 2, icon_size, icon_size)

        text_left = margin
        text_width = w - margin * 3 - icon_size
        self._label = QtWidgets.QLabel(message, self)
        self._label.setAlignment(QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft)
        self._label.setStyleSheet(f'color:{p.text_primary}; font-size:{dpix(14)}px;')
        self._label.setGeometry(text_left, 0, text_width, h)
        self._drag_pos = None

        self._base_message = message.rstrip('.')
        self._dot_count = -1
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._animate_dots)
        self._timer.setInterval(900)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() & QtCore.Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None

    def _animate_dots(self):
        self._dot_count = (self._dot_count + 1) % 4
        self._label.setText(self._base_message + '.' * self._dot_count)

    def show(self):
        super().show()
        self._timer.start()
        screen = QtWidgets.QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move(
                geo.x() + (geo.width() - self.width()) // 2,
                geo.y() + (geo.height() - self.height()) // 2,
            )
        QtWidgets.QApplication.processEvents()
