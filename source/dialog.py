from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPushButton,
    QHBoxLayout, QLineEdit, QSizePolicy, QApplication, QStyle
)
from PySide6.QtCore import Qt


class BaseDialog(QDialog):
    def __init__(self, message, title="Dialog", buttons=("OK", "Cancel"),
                 icon_type=QStyle.SP_MessageBoxInformation, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowModality(Qt.ApplicationModal)
        self.setMinimumWidth(300)

        self.result_text = None

        # アイコン
        icon = self.style().standardIcon(icon_type)
        icon_label = QLabel()
        icon_label.setPixmap(icon.pixmap(32, 32))

        # メッセージ
        self.message_label = QLabel(message)
        self.message_label.setWordWrap(True)
        self.message_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        # メッセージとアイコンの横並び
        message_layout = QHBoxLayout()
        message_layout.addWidget(icon_label)
        message_layout.addWidget(self.message_label)

        # ボタン
        self.btn_layout = QHBoxLayout()
        self.btn_layout.addStretch()
        for btn_text in buttons:
            btn = QPushButton(btn_text)
            btn.clicked.connect(lambda _, text=btn_text: self._on_button(text))
            self.btn_layout.addWidget(btn)

        # メインレイアウト
        self.main_layout = QVBoxLayout()
        self.main_layout.addLayout(message_layout)
        # ★サブクラスがここにウィジェットを追加できる
        self.content_layout = QVBoxLayout()
        self.main_layout.addLayout(self.content_layout)
        self.main_layout.addLayout(self.btn_layout)

        self.setLayout(self.main_layout)

    def _on_button(self, text):
        self.result_text = text
        self.accept()


class ConfirmDialog(BaseDialog):
    @staticmethod
    def ask(message, title="Confirm", buttons=("OK", "Cancel"), parent=None):
        dialog = ConfirmDialog(message, title, buttons, parent=parent)
        dialog.exec()
        return dialog.result_text


class InputDialog(BaseDialog):
    def __init__(self, message, title="Input", buttons=("OK", "Cancel"), parent=None):
        super().__init__(message, title, buttons, parent=parent)
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("入力してください…")
        self.content_layout.addWidget(self.input_edit)

    @staticmethod
    def get_text(message, title="Input", buttons=("OK", "Cancel"), parent=None):
        dialog = InputDialog(message, title, buttons, parent=parent)
        dialog.exec()
        if dialog.result_text and dialog.result_text == buttons[0]:  # OKが押された場合
            return dialog.input_edit.text()
        else:
            return None
