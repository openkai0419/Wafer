import py_compile
from unittest.mock import MagicMock, patch

from wafer.app.indexer.dispatch.parser_dispatcher import ParserDispatcher, _DISPATCH_INTERVAL


def test_compile():
    py_compile.compile("wafer/app/indexer/dispatch/parser_dispatcher.py")


def test_constants():
    assert _DISPATCH_INTERVAL > 0


def test_terminate_parsers_requests_shutdown_before_fallback(tmp_path):
    scheduler = MagicMock()
    writer = MagicMock()
    progress = MagicMock()
    db_path = tmp_path / "test.db"
    dispatcher = ParserDispatcher("testdb", db_path, scheduler, writer, progress, parsers=["sample"])
    dispatcher._node = MagicMock()

    with patch.object(dispatcher, "_wait_parser_stopped", return_value=False), patch(
        "wafer.app.indexer.dispatch.parser_dispatcher.AppProcess.terminate_cmd"
    ) as terminate_cmd:
        dispatcher._terminate_parsers()

    dispatcher._node.send.assert_called_once_with(
        "worker.shutdown",
        {"plugin": "sample"},
        dst="parser-sample",
        db="testdb",
    )
    terminate_cmd.assert_called_once_with("--parser", "testdb", "--plugin", "sample", recursive=True)


def test_terminate_parsers_skips_fallback_when_graceful_stop_succeeds(tmp_path):
    scheduler = MagicMock()
    writer = MagicMock()
    progress = MagicMock()
    db_path = tmp_path / "test.db"
    dispatcher = ParserDispatcher("testdb", db_path, scheduler, writer, progress, parsers=["sample"])
    dispatcher._node = MagicMock()

    with patch.object(dispatcher, "_wait_parser_stopped", return_value=True), patch(
        "wafer.app.indexer.dispatch.parser_dispatcher.AppProcess.terminate_cmd"
    ) as terminate_cmd:
        dispatcher._terminate_parsers()

    dispatcher._node.send.assert_called_once()
    terminate_cmd.assert_not_called()
