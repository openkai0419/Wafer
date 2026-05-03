from PySide6.QtCore import QSignalBlocker, QSize, Qt, Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QPushButton, QWidget
from ....core.lang.manager import t
from ....core.qt.icon_engine import themed_icon
from ....core.color.theme import ThemeManager

class NoWheelComboBox(QComboBox):
    def wheelEvent(self, event):
        event.ignore()

class ComboBoxWithButtons(QWidget):
    addClicked = Signal()
    removeClicked = Signal()
    textChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.combo = NoWheelComboBox()
        self.button_add = QPushButton()
        self.button_add.setIcon(themed_icon("plus"))
        self.button_remove = QPushButton()
        self.button_remove.setIcon(themed_icon("minus"))
        self.combo.currentIndexChanged.connect(self.on_changed)
        self.button_add.setToolTip(t("Add item"))
        self.button_remove.setToolTip(t("Remove current item"))
        self._current_text = None
        layout = QHBoxLayout()
        layout.addWidget(self.button_add)
        layout.addWidget(self.button_remove)
        layout.addWidget(self.combo)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setLayout(layout)
        self.button_add.clicked.connect(self.addClicked.emit)
        self.button_remove.clicked.connect(self.removeClicked.emit)
        ThemeManager.instance().on_theme_changed.connect(self._on_theme_changed)

    def _on_theme_changed(self, palette):
        self.button_add.setIcon(themed_icon("plus"))
        self.button_remove.setIcon(themed_icon("minus"))
    
    def resizeEvent(self, event):
        h = self.combo.height()
        self.button_add.setFixedSize(h, h)
        self.button_remove.setFixedSize(h, h)
        isz = max(1, int(h * 0.55))
        icon_sz = QSize(isz, isz)
        self.button_add.setIconSize(icon_sz)
        self.button_remove.setIconSize(icon_sz)
        return super().resizeEvent(event)

    def addItem(self, text):
        with QSignalBlocker(self.combo):
            self.combo.addItem(text)
        self._current_text = self.currentText()

    def removeItem(self, text):
        idx = self.combo.findText(text, Qt.MatchExactly)
        if idx >= 0:
            with QSignalBlocker(self.combo):
                self.combo.removeItem(idx)
            self._current_text = self.currentText()

    def setCurrentText(self, text):
        idx = self.combo.findText(text, Qt.MatchExactly)
        if idx >= 0:
            with QSignalBlocker(self.combo):
                self.combo.setCurrentIndex(idx)
            self._current_text = self.currentText()

    def setCurrentIndex(self, idx):
        if 0 <= idx < self.combo.count():
            self.combo.setCurrentIndex(idx)

    def getCurrentIndex(self):
        return self.combo.currentIndex()

    def on_changed(self):
        text = self.currentText()
        if self._current_text != text:
            self.textChanged.emit(text)
        self._current_text = text

    def count(self):
        return self.combo.count()

    def currentText(self):
        return self.combo.currentText()

    def setItems(self, items):
        with QSignalBlocker(self.combo):
            self.combo.clear()
            self.combo.addItems(items)
        self._current_text = self.currentText()
