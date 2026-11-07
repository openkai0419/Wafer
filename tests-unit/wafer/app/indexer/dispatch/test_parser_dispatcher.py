from unittest.mock import MagicMock, patch

import pytest

from wafer.app.indexer.db_writer import DatabaseWriter
from wafer.app.indexer.dispatch.parser_dispatcher import ParserDispatcher
from wafer.core.db.db_utils import open_readonly


def test_terminate_parsers_requests_shutdown_before_fallback(tmp_path):
    scheduler = MagicMock()
    writer = MagicMock()
    progress = MagicMock()
    db_path = tmp_path / "test.db"
    dispatcher = ParserDispatcher("testdb", db_path, scheduler, writer, progress, parsers=["sample"])
    dispatcher._node = MagicMock()

    with patch.object(dispatcher, "_wait_parser_stopped", return_value=False), patch("wafer.app.indexer.dispatch.parser_dispatcher.AppProcess.terminate_cmd") as terminate_cmd:
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

    with patch.object(dispatcher, "_wait_parser_stopped", return_value=True), patch("wafer.app.indexer.dispatch.parser_dispatcher.AppProcess.terminate_cmd") as terminate_cmd:
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
    dispatcher._node.nudge_undelivered.return_value = False
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
    sent = dispatcher._node.send_reliable.call_args
    assert sent.args[0] == "parse.batch"
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
    dispatcher._node.send_reliable.assert_not_called()


class _BusyLane:
    """The background lane during a flush: anything submitted waits until the test runs it."""

    def __init__(self):
        self.tasks = []
        self.note_activity = MagicMock()

    def submit(self, task):
        self.tasks.append(task)

    def run_all(self):
        tasks, self.tasks = self.tasks, []
        for task in tasks:
            task.run()
            if task.on_complete:
                task.on_complete()


@pytest.fixture
def real_db_dispatcher(tmp_path):
    writer = DatabaseWriter(tmp_path / "test.db")
    writer.start()
    writer.initialize()
    sources = ["src0", "src1", "src2"]
    writer.db.upsert_basic_sources([(s, f"hash-{s}", 1, 1.0) for s in sources], [])
    writer.insert_pending(sources, ["sample"])
    lane = _BusyLane()
    dispatcher = ParserDispatcher("testdb", tmp_path / "test.db", lane, writer, MagicMock(), parsers=["sample"])
    dispatcher._node = MagicMock()
    dispatcher._node.nudge_undelivered.return_value = False
    dispatcher._read_conn = open_readonly(tmp_path / "test.db")
    with patch("wafer.app.indexer.dispatch.parser_dispatcher.parser_resolver") as resolver:
        resolver.status_name.return_value = "sample"
        resolver.batch_size.return_value = 2
        resolver.trigger_keys.return_value = ()
        yield dispatcher, writer, lane, resolver
    dispatcher._read_conn.close()
    writer.close()


def _statuses(writer):
    return dict(writer.db.conn.execute("SELECT source, status FROM collection_status WHERE collector = 'sample'").fetchall())


def _sent_paths(dispatcher):
    return [call.args[1]["paths"] for call in dispatcher._node.send_reliable.call_args_list]


def test_source_set_pending_again_is_not_taken_back_by_a_late_mark(real_db_dispatcher):
    dispatcher, writer, lane, _resolver = real_db_dispatcher

    dispatcher._dispatch_pending()
    sent = _sent_paths(dispatcher)[0]
    writer.db.upsert_collection_results([], [], [], [(s, "sample", "ok", 1.0) for s in sent])
    writer.insert_pending(sent, ["sample"])
    lane.run_all()

    assert all(_statuses(writer)[s] == "pending" for s in sent)


def test_trigger_arriving_after_the_skip_is_not_overwritten_by_a_late_mark(real_db_dispatcher):
    dispatcher, writer, lane, resolver = real_db_dispatcher
    resolver.trigger_keys.return_value = ("exiftool.PNG:Comment",)

    with patch.object(writer.db, "get_trigger_metadata", return_value={}):
        dispatcher._dispatch_pending()
    assert set(_statuses(writer).values()) == {"ok", "pending"}
    skipped = [s for s, status in _statuses(writer).items() if status == "ok"]
    writer.insert_pending(skipped, ["sample"])
    lane.run_all()

    assert all(_statuses(writer)[s] == "pending" for s in skipped)


def test_sources_are_dispatched_before_the_batch_leaves(real_db_dispatcher):
    dispatcher, writer, _lane, _resolver = real_db_dispatcher
    seen = {}
    dispatcher._node.send_reliable.side_effect = lambda *a, **k: seen.update(_statuses(writer))

    dispatcher._dispatch_pending()

    assert sorted(seen.values()) == ["dispatched", "dispatched", "pending"]


def test_next_dispatch_sends_the_rest_while_the_lane_is_busy(real_db_dispatcher):
    dispatcher, _writer, _lane, _resolver = real_db_dispatcher

    dispatcher._dispatch_pending()
    dispatcher._dispatch_pending()

    assert sorted(p for batch in _sent_paths(dispatcher) for p in batch) == ["src0", "src1", "src2"]


def test_undelivered_batch_holds_back_the_next_one(real_db_dispatcher):
    dispatcher, writer, _lane, _resolver = real_db_dispatcher
    dispatcher._node.nudge_undelivered.return_value = True

    dispatcher._dispatch_pending()

    dispatcher._node.nudge_undelivered.assert_called_once_with("parse.batch", dst="parser-sample", db="testdb")
    dispatcher._node.send_reliable.assert_not_called()
    assert set(_statuses(writer).values()) == {"pending"}


def test_stale_rows_are_reset_before_the_first_dispatch(tmp_path, monkeypatch):
    import threading

    from wafer.app.indexer.dispatch import parser_dispatcher

    monkeypatch.setattr(parser_dispatcher, "_DISPATCH_INTERVAL", 0.01)
    calls = []
    writer = MagicMock()
    writer.reset_stale.side_effect = lambda names: calls.append(("reset", names))
    dispatcher = ParserDispatcher("testdb", tmp_path / "test.db", MagicMock(), writer, MagicMock(), parsers=["sample"])
    dispatched = threading.Event()

    def dispatch():
        calls.append(("dispatch",))
        dispatched.set()

    dispatcher._dispatch_pending = dispatch
    with patch("wafer.app.indexer.dispatch.parser_dispatcher.parser_resolver") as resolver:
        resolver.status_name.return_value = "sample"
        thread = threading.Thread(target=dispatcher._dispatch_loop, daemon=True)
        thread.start()
        assert dispatched.wait(timeout=3.0)
        dispatcher._stop.set()
        dispatcher._dispatch_event.set()
        thread.join(timeout=3.0)

    assert calls[:2] == [("reset", ["sample"]), ("dispatch",)]
