import sys
from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtWidgets import QApplication, QComboBox, QHBoxLayout, QPushButton, QWidget
from ...lang.manager import TranslatorMixin

class ComboBoxWithButtons(QWidget, TranslatorMixin):
    addClicked = Signal()
    removeClicked = Signal()
    textChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.combo = QComboBox()
        self.button_add = QPushButton('+')
        self.button_remove = QPushButton('-')
        self.combo.currentIndexChanged.connect(self.on_changed)
        self.button_add.setToolTip(self.t.tr('Add item'))
        self.button_remove.setToolTip(self.t.tr('Remove current item'))
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

    def resizeEvent(self, event):
        h = self.combo.height()
        self.button_add.setFixedSize(h, h)
        self.button_remove.setFixedSize(h, h)
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
        
if __name__ == '__main__':
    app = QApplication(sys.argv)
    w = ComboBoxWithButtons()
    w.setItems(['Apple', 'Banana', 'Cherry'])
    w.addClicked.connect(lambda: print('Add button clicked'))
    w.removeClicked.connect(lambda: print('Remove button clicked'))
    w.textChanged.connect(lambda text: print(f'textChanged: {text}'))
    w.show()
    sys.exit(app.exec())
