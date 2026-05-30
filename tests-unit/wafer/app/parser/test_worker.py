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
    assert "worker.shutdown" in worker._node._handlers


def test_on_notify_calls_plugin():
    worker = _make_worker()
    worker._plugin.on_notify = MagicMock()

    mock_msg = MagicMock()
    result = worker._on_notify(mock_msg)

    worker._plugin.on_notify.assert_called_once()
    assert result is True


def test_worker_shutdown_message_sets_stop():
    worker = _make_worker()
    mock_msg = MagicMock()
    result = worker._on_shutdown(mock_msg)
    assert result is True
    assert worker._stop.is_set()


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


def test_stop_calls_plugin_shutdown_once():
    worker = _make_worker()
    worker._plugin.shutdown = MagicMock()
    worker.stop()
    worker.stop()
    worker._plugin.shutdown.assert_called_once()


def test_stop_continues_when_plugin_shutdown_fails():
    worker = _make_worker()
    worker._plugin.shutdown = MagicMock(side_effect=RuntimeError("boom"))
    worker.stop()
    assert worker._stop.is_set()
    worker._node.stop.assert_called()


def test_constants():
    from wafer.app.parser.worker import _SHUTDOWN_WAIT

    assert _SHUTDOWN_WAIT > 0


def test_worker_uses_parser_execution_settings():
    worker = _make_worker()
    assert worker._max_workers == parser_resolver.max_workers(worker.plugin_name)
    assert worker._batch_timeout == parser_resolver.batch_timeout(worker.plugin_name)
