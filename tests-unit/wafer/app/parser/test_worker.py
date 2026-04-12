import py_compile
from unittest.mock import MagicMock, patch

from wafer.plugin.parser.handler import parser_resolver


def test_compile():
    py_compile.compile("wafer/app/parser/worker.py")


def _make_worker():
    from wafer.app.parser.worker import ParserWorker

    names = parser_resolver.names()
    if not names:
        import pytest

        pytest.skip("No parser plugins registered")
    name = next(iter(names))
    worker = ParserWorker("test_db", name)
    worker._node = MagicMock()
    return worker


def test_notify_subscribed():
    from wafer.app.parser.worker import ParserWorker

    names = parser_resolver.names()
    if not names:
        import pytest

        pytest.skip("No parser plugins registered")
    name = next(iter(names))
    worker = ParserWorker("test_db", name)
    assert "plugin.notify" in worker._node._handlers


def test_on_notify_calls_plugin():
    worker = _make_worker()
    worker._plugin.on_notify = MagicMock()

    mock_msg = MagicMock()
    result = worker._on_notify(mock_msg)

    worker._plugin.on_notify.assert_called_once()
    assert result is True


def test_handle_batch_rejects_when_stopped():
    from wafer.core.ipc.message import Message

    worker = _make_worker()
    worker._stop.set()
    msg = Message.build(
        "parse.batch",
        {"paths": ["/test/a.jpg"], "file_info": {}, "metadata": {}},
        src="test",
        dst="parser",
        db="test_db",
    )
    result = worker._handle_batch(msg)
    assert result is True


def test_shutdown_cancel_futures():
    worker = _make_worker()
    worker._node.stop = MagicMock()
    worker.stop()
    assert worker._stop.is_set()


def test_constants():
    from wafer.app.parser.worker import _TASK_TIMEOUT, _SHUTDOWN_WAIT

    assert _TASK_TIMEOUT > 0
    assert _SHUTDOWN_WAIT > 0
