import threading

import numpy as np
import pytest


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr("wafer.plugin.config._ini_path", lambda: str(tmp_path / "viewer_plugins.ini"))


def test_dropped_image_decodes_off_the_main_thread(qtbot, monkeypatch):
    from extensions.florence.panel import FlorenceSettingsWidget
    from wafer.qt.common.thread import utility_pool

    w = FlorenceSettingsWidget()
    qtbot.addWidget(w)
    threads = []

    def fake_load(path, size):
        threads.append(threading.current_thread())
        return np.zeros((8, 16, 3), dtype=np.uint8)

    monkeypatch.setattr("extensions.florence.panel.image_loader_resolver.load", fake_load)
    monkeypatch.setattr(w, "_on_preview_clicked", lambda: None)
    w._set_preview_path("/a.png")
    qtbot.waitUntil(lambda: w._original_pixmap is not None, timeout=5000)
    assert w._dispatcher._pool is utility_pool
    assert threads and threads[0] is not threading.main_thread()
    assert w._original_pixmap.width() == 16
