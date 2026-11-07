from unittest.mock import MagicMock

import pytest
from PySide6 import QtWidgets

from wafer.qt.widgets.restart_prompt import ask_restart_all


@pytest.mark.parametrize(("clicked", "runs"), [("Restart", True), ("Not Now", False)])
def test_only_the_restart_button_restarts(monkeypatch, clicked, runs):
    shown = {}

    def fake_exec(message_box):
        shown["title"], shown["text"] = message_box.windowTitle(), message_box.text()
        shown["buttons"] = {button.text(): button for button in message_box.buttons()}
        shown["default"] = message_box.defaultButton().text()

    run = MagicMock()
    monkeypatch.setattr(QtWidgets.QMessageBox, "exec", fake_exec)
    monkeypatch.setattr(QtWidgets.QMessageBox, "clickedButton", lambda self: shown["buttons"][clicked])
    monkeypatch.setattr("wafer.qt.widgets.restart_prompt.Command.run", run)

    ask_restart_all("Saved.")

    assert shown["title"] == "Restart Required" and shown["text"] == "Saved."
    assert shown["default"] == "Restart"
    assert run.call_args_list == ([(("win.restart_all",),)] if runs else [])
