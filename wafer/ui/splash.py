from PySide6 import QtWidgets, QtCore, QtGui

from ..utils.formatting import dpix
from ..core.color.theme import ThemeManager


class InstallSplash(QtWidgets.QWidget):
    def __init__(self, title: str, icon: QtGui.QIcon = None, message: str = "Installing plugin dependencies.\nThis may take few minutes...", show_log: bool = True, cancel_label: str | None = None):
        super().__init__()
        self.setWindowTitle(title)
        if icon and not icon.isNull():
            self.setWindowIcon(icon)
        self.setWindowFlags(QtCore.Qt.Window | QtCore.Qt.FramelessWindowHint)
        p = ThemeManager.instance().palette
        self.setStyleSheet(f"background:{p.bg_secondary};")

        header_h = dpix(80)
        log_h = dpix(220) if show_log else 0
        button_h = dpix(40) if cancel_label else 0
        margin = dpix(16)
        icon_size = dpix(48)
        w = dpix(560) if show_log else dpix(360)
        h = header_h + log_h + button_h
        self.setFixedSize(w, h)

        icon_label = QtWidgets.QLabel(self)
        if icon and not icon.isNull():
            icon_label.setPixmap(icon.pixmap(icon_size, icon_size))
        icon_label.setFixedSize(icon_size, icon_size)
        icon_label.setAlignment(QtCore.Qt.AlignCenter)
        icon_label.setGeometry(w - margin - icon_size, (header_h - icon_size) // 2, icon_size, icon_size)

        text_left = margin
        text_width = w - margin * 3 - icon_size
        self._label = QtWidgets.QLabel(message, self)
        self._label.setAlignment(QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft)
        self._label.setStyleSheet(f"color:{p.text_primary}; font-size:{dpix(14)}px;")
        self._label.setGeometry(text_left, 0, text_width, header_h)

        self._log = None
        if show_log:
            self._log = QtWidgets.QPlainTextEdit(self)
            self._log.setReadOnly(True)
            self._log.setFrameShape(QtWidgets.QFrame.NoFrame)
            font = QtGui.QFont("Consolas")
            font.setStyleHint(QtGui.QFont.Monospace)
            font.setPixelSize(dpix(11))
            self._log.setFont(font)
            self._log.setStyleSheet(f"QPlainTextEdit{{background:{p.bg_primary};color:{p.text_secondary};padding:{dpix(6)}px;}}")
            self._log.setGeometry(margin, header_h, w - margin * 2, log_h - margin)
            self._log.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
            self._log.setMaximumBlockCount(2000)

        self.cancel_button = None
        if cancel_label:
            btn = QtWidgets.QPushButton(cancel_label, self)
            btn_w = dpix(140)
            btn.setGeometry(w - margin - btn_w, header_h + log_h - margin // 2, btn_w, button_h - margin // 2)
            self.cancel_button = btn

        self._drag_pos = None
        self._base_message = message.rstrip(".")
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
        self._label.setText(self._base_message + "." * self._dot_count)

    def set_message(self, text: str):
        self._base_message = text.rstrip(".")
        self._dot_count = -1
        self._animate_dots()

    def append_log(self, line: str):
        if self._log is None or not line:
            return
        self._log.appendPlainText(line)
        bar = self._log.verticalScrollBar()
        bar.setValue(bar.maximum())

    def replace_log(self, lines):
        if self._log is None:
            return
        text = "\n".join(lines) if lines else ""
        if text == self._log.toPlainText():
            return
        self._log.setPlainText(text)
        bar = self._log.verticalScrollBar()
        bar.setValue(bar.maximum())

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
