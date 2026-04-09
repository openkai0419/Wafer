import py_compile
from unittest.mock import MagicMock, patch

from wafer.plugin.detacher.handler import detacher_resolver


def test_compile():
    py_compile.compile("wafer/app/detacher/worker.py")


def _make_worker():
    from wafer.app.detacher.worker import DetacherWorker

    names = detacher_resolver.names()
    if not names:
        import pytest

        pytest.skip("No detacher plugins registered")
    name = next(iter(names))
    worker = DetacherWorker("test_db", name)
    worker._node = MagicMock()
    return worker


def test_notify_subscribed():
    from wafer.app.detacher.worker import DetacherWorker

    names = detacher_resolver.names()
    if not names:
        import pytest

        pytest.skip("No detacher plugins registered")
    name = next(iter(names))
    worker = DetacherWorker("test_db", name)
    assert "plugin.notify" in worker._node._handlers


def test_on_notify_calls_plugin():
    worker = _make_worker()
    worker._plugin.on_notify = MagicMock()

    mock_msg = MagicMock()
    result = worker._on_notify(mock_msg)

    worker._plugin.on_notify.assert_called_once()
    assert result is True
