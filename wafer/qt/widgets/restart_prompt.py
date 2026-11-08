from PySide6 import QtWidgets

from ...core.lang.manager import t
from ..commands.bridge import Command


def ask_restart_all(body: str, parent: QtWidgets.QWidget | None = None) -> None:
    msg = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Question, t("Restart Required"), body, parent=parent)
    restart_btn = msg.addButton(t("Restart"), QtWidgets.QMessageBox.AcceptRole)
    msg.addButton(t("Not Now"), QtWidgets.QMessageBox.RejectRole)
    msg.setDefaultButton(restart_btn)
    msg.exec()
    if msg.clickedButton() == restart_btn:
        Command.run("win.restart_all")
