from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPushButton,
    QHBoxLayout, QLineEdit, QSizePolicy, QApplication, QStyle
)
from PySide6.QtCore import Qt, QTimer
from ..image_setting.translation import TranslatorMixin


class BaseDialog(QDialog):
    def __init__(self, message, title="Dialog", buttons=("OK", "Cancel"),
                 icon_type=QStyle.SP_MessageBoxInformation, parent=None):
        super().__init__(parent)
        self.message = message
        self.setWindowTitle(title)
        self.setWindowModality(Qt.ApplicationModal)

        self.result_text = None

        # Icon
        icon = self.style().standardIcon(icon_type)
        icon_label = QLabel()
        icon_label.setPixmap(icon.pixmap(32, 32))

        # Message
        self.message_label = QLabel(message)
        self.message_label.setWordWrap(True)
        self.message_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        # Layout: icon next to message
        message_layout = QHBoxLayout()
        message_layout.addWidget(icon_label)
        message_layout.addWidget(self.message_label)

        # Buttons
        self.btn_layout = QHBoxLayout()
        self.btn_layout.addStretch()
        for btn_text in buttons:
            btn = QPushButton(btn_text)
            btn.clicked.connect(lambda _, text=btn_text: self._on_button(text))
            self.btn_layout.addWidget(btn)

        # Main layout
        self.main_layout = QVBoxLayout()
        self.main_layout.addLayout(message_layout)
        # Subclasses can add widgets here
        self.content_layout = QVBoxLayout()
        self.main_layout.addLayout(self.content_layout)
        self.main_layout.addLayout(self.btn_layout)

        self.setLayout(self.main_layout)

    def showEvent(self, event):
        super().showEvent(event)
        self.adjust_to_message()

    def adjust_to_message(self):
        min_width = 300
        max_width = 800
        message = self.message

        metrics = self.message_label.fontMetrics()
        # 行ごとに計算
        lines = message.splitlines()
        line_widths = [metrics.boundingRect(line).width() for line in lines]
        max_line_width = max(line_widths, default=min_width) + 50  # 余白

        final_width = max(min_width, min(max_line_width, max_width))

        self.message_label.setMinimumWidth(final_width)
        self.adjustSize()

        
    def _on_button(self, text):
        self.result_text = text
        self.accept()


class ConfirmDialog(BaseDialog):
    @staticmethod
    def ask(message, title="Confirm", buttons=("OK", "Cancel"), parent=None):
        dialog = ConfirmDialog(message, title, buttons, parent=parent)
        dialog.exec()
        return dialog.result_text


class InputDialog(BaseDialog, TranslatorMixin):
    def __init__(self, message, title="Input", buttons=("OK", "Cancel"), parent=None):
        super().__init__(message, title, buttons, parent=parent)
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText(self.t.tr("Please enter text..."))
        self.content_layout.addWidget(self.input_edit)

    @staticmethod
    def get_text(message, title="Input", buttons=("OK", "Cancel"), parent=None):
        dialog = InputDialog(message, title, buttons, parent=parent)
        dialog.exec()
        if dialog.result_text and dialog.result_text == buttons[0]:  # OK clicked
            return dialog.input_edit.text()
        else:
            return None
