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


def _dispatcher_for_pending(tmp_path):
    scheduler = MagicMock()
    scheduler.submit = lambda task: task.run()
    writer = MagicMock()
    progress = MagicMock()
    db_path = tmp_path / "test.db"
    dispatcher = ParserDispatcher("testdb", db_path, scheduler, writer, progress, parsers=["sample"])
    dispatcher._node = MagicMock()
    return dispatcher, writer


def test_dispatch_pending_marks_untriggered_collected_and_skips_send(tmp_path):
    dispatcher, writer = _dispatcher_for_pending(tmp_path)
    cursor = MagicMock()
    cursor.fetchall.return_value = [
        ("/a.png", 1.0, 10, "h1"),
        ("/b.png", 1.0, 20, "h2"),
    ]
    dispatcher._read_conn = MagicMock()
    dispatcher._read_conn.cursor.return_value = cursor
    writer.db.get_trigger_metadata.return_value = {"/a.png": {"exiftool.PNG:Comment": "{}"}}

    with patch("wafer.app.indexer.dispatch.parser_dispatcher.parser_resolver") as pr:
        pr.status_name.return_value = "novelai"
        pr.batch_size.return_value = 300
        pr.trigger_keys.return_value = ("exiftool.PNG:Comment",)
        dispatcher._dispatch_pending()

    writer.mark_collected.assert_called_once_with(["/b.png"], "novelai")
    sent = dispatcher._node.send.call_args
    assert sent.kwargs["dst"] == "parser-sample"
    assert sent.args[1]["paths"] == ["/a.png"]


def test_dispatch_pending_skips_send_when_all_untriggered(tmp_path):
    dispatcher, writer = _dispatcher_for_pending(tmp_path)
    cursor = MagicMock()
    cursor.fetchall.return_value = [("/a.png", 1.0, 10, "h1")]
    dispatcher._read_conn = MagicMock()
    dispatcher._read_conn.cursor.return_value = cursor
    writer.db.get_trigger_metadata.return_value = {}

    with patch("wafer.app.indexer.dispatch.parser_dispatcher.parser_resolver") as pr:
        pr.status_name.return_value = "novelai"
        pr.batch_size.return_value = 300
        pr.trigger_keys.return_value = ("exiftool.PNG:Comment",)
        dispatcher._dispatch_pending()

    writer.mark_collected.assert_called_once_with(["/a.png"], "novelai")
    dispatcher._node.send.assert_not_called()
