from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPushButton,
    QHBoxLayout, QApplication, QStyle, QSizePolicy
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap


class ConfirmDialog(QDialog):
    def __init__(self, message, title="Confirm", buttons=("OK", "Cancel"), parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowModality(Qt.ApplicationModal)
        self.setMinimumWidth(300)

        self.result_text = None

        # アイコン取得
        icon = self.style().standardIcon(QStyle.SP_MessageBoxInformation)
        icon_label = QLabel()
        icon_label.setPixmap(icon.pixmap(32, 32))

        # メッセージラベル
        message_label = QLabel(message)
        message_label.setWordWrap(True)
        message_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # 横並びにするレイアウト（アイコン + メッセージ）
        message_layout = QHBoxLayout()
        message_layout.addWidget(icon_label)
        message_layout.addWidget(message_label)

        # ボタンレイアウト
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        for btn_text in buttons:
            btn = QPushButton(btn_text)
            btn.clicked.connect(lambda _, text=btn_text: self._on_button(text))
            btn_layout.addWidget(btn)

        # メインレイアウト
        layout = QVBoxLayout()
        layout.addLayout(message_layout)
        layout.addLayout(btn_layout)
        self.setLayout(layout)

    def _on_button(self, text):
        self.result_text = text
        self.accept()

    @staticmethod
    def ask(message, title="Confirm", buttons=("OK", "Cancel"), parent=None):
        dialog = ConfirmDialog(message, title, buttons, parent)
        dialog.exec()
        return dialog.result_text
