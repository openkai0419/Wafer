from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from ...utils.formatting import dpix
from ...core.lang.manager import t


def open_value_viewer(parent: QtWidgets.QWidget | None, key: str, text: str) -> None:
    dlg = QtWidgets.QDialog(parent)
    dlg.setWindowTitle(t("Value viewer - {key}", key=key))
    dlg.resize(dpix(900), dpix(600))
    lay = QtWidgets.QVBoxLayout(dlg)

    key_label = QtWidgets.QLabel(key, dlg)
    key_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
    key_label.setWordWrap(True)
    f = key_label.font()
    f.setBold(True)
    key_label.setFont(f)
    lay.addWidget(key_label)

    edit = QtWidgets.QPlainTextEdit(dlg)
    edit.setReadOnly(True)
    edit.setPlainText(text)
    lay.addWidget(edit)

    btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close, parent=dlg)
    btns.rejected.connect(dlg.reject)
    lay.addWidget(btns)
    dlg.exec()
