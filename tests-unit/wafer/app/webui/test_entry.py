from unittest.mock import MagicMock

import pytest

from wafer.app import startup
from wafer.app.webui import entry, window
from wafer.app.webui.backend import server


def test_run_ui_keeps_running_until_the_server_has_stopped(monkeypatch):
    monkeypatch.setattr(server, "WebServer", MagicMock())
    monkeypatch.setattr(window, "WebUIWindow", MagicMock())
    monkeypatch.setattr(startup, "StartupTasks", MagicMock())
    app = MagicMock()
    app.exec.return_value = 0

    with pytest.raises(SystemExit):
        entry.run_ui(app, MagicMock(), "127.0.0.1", 8787, open_browser=False)

    app.setQuitOnLastWindowClosed.assert_called_once_with(False)
