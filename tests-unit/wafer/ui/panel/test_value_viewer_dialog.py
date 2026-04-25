from PySide6 import QtWidgets

from wafer.ui.panel.value_viewer_dialog import open_value_viewer


def test_open_value_viewer_shows_full_text(qtbot, monkeypatch):
    captured: dict = {}

    def fake_exec(self):
        edit = self.findChild(QtWidgets.QPlainTextEdit)
        captured["text"] = edit.toPlainText()
        captured["read_only"] = edit.isReadOnly()
        captured["title"] = self.windowTitle()
        return 0

    monkeypatch.setattr(QtWidgets.QDialog, "exec", fake_exec)
    long_text = "abcdefg" * 5000
    open_value_viewer(None, "MyKey", long_text)
    assert captured["text"] == long_text
    assert captured["read_only"] is True
    assert "MyKey" in captured["title"]
