import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from wafer.app.indexer.db_writer import DatabaseWriter
from wafer.app.indexer.dispatch.collector_dispatcher import CollectorDispatcher
from wafer.core.db.db_utils import open_readonly
from wafer.plugin.collector.handler import collector_resolver


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
    writer.insert_pending(sources, ["exif"])
    lane = _BusyLane()
    dispatcher = CollectorDispatcher("testdb", tmp_path / "test.db", lane, writer, MagicMock(), collectors=["exif"])
    dispatcher._node = MagicMock()
    dispatcher._node.nudge_undelivered.return_value = False
    dispatcher._read_conn = open_readonly(tmp_path / "test.db")
    with patch.object(collector_resolver, "batch_size", return_value=2):
        yield dispatcher, writer, lane
    dispatcher._read_conn.close()
    writer.close()


def _statuses(writer):
    return dict(writer.db.conn.execute("SELECT source, status FROM collection_status WHERE collector = 'exif'").fetchall())


def _sent_paths(dispatcher):
    return [call.args[1]["paths"] for call in dispatcher._node.send_reliable.call_args_list]


def test_source_set_pending_again_is_not_taken_back_by_a_late_mark(real_db_dispatcher):
    dispatcher, writer, lane = real_db_dispatcher

    dispatcher._dispatch_pending()
    sent = _sent_paths(dispatcher)[0]
    writer.db.upsert_collection_results([], [], [], [(s, "exif", "ok", 1.0) for s in sent])
    writer.insert_pending(sent, ["exif"])
    lane.run_all()

    assert all(_statuses(writer)[s] == "pending" for s in sent)


def test_sources_are_dispatched_before_the_batch_leaves(real_db_dispatcher):
    dispatcher, writer, _lane = real_db_dispatcher
    seen = {}
    dispatcher._node.send_reliable.side_effect = lambda *a, **k: seen.update(_statuses(writer))

    dispatcher._dispatch_pending()

    assert sorted(seen.values()) == ["dispatched", "dispatched", "pending"]


def test_next_dispatch_sends_the_rest_while_the_lane_is_busy(real_db_dispatcher):
    dispatcher, _writer, _lane = real_db_dispatcher

    dispatcher._dispatch_pending()
    dispatcher._dispatch_pending()

    assert sorted(p for batch in _sent_paths(dispatcher) for p in batch) == ["src0", "src1", "src2"]


def test_batch_goes_to_the_collector_through_the_outbox(real_db_dispatcher):
    dispatcher, _writer, _lane = real_db_dispatcher

    dispatcher._dispatch_pending()

    call = dispatcher._node.send_reliable.call_args
    assert call.args[0] == "collect.batch"
    assert call.kwargs == {"dst": "collector-exif", "db": "testdb"}
    assert sorted(call.args[1]["file_info"]) == sorted(call.args[1]["paths"])
    dispatcher._node.send.assert_not_called()


def test_a_batch_that_could_not_be_sent_is_sent_again(real_db_dispatcher):
    dispatcher, writer, _lane = real_db_dispatcher
    dispatcher._node.send_reliable.side_effect = [sqlite3.OperationalError("database is locked"), None]

    with pytest.raises(sqlite3.OperationalError):
        dispatcher._dispatch_pending()
    assert set(_statuses(writer).values()) == {"pending"}
    dispatcher._progress.increment.assert_not_called()

    dispatcher._dispatch_pending()
    first, second = _sent_paths(dispatcher)
    assert second == first
    assert sorted(_statuses(writer)[s] for s in second) == ["dispatched", "dispatched"]


def test_undelivered_batch_holds_back_the_next_one(real_db_dispatcher):
    dispatcher, writer, _lane = real_db_dispatcher
    dispatcher._node.nudge_undelivered.return_value = True

    dispatcher._dispatch_pending()

    dispatcher._node.nudge_undelivered.assert_called_once_with("collect.batch", dst="collector-exif", db="testdb")
    dispatcher._node.send_reliable.assert_not_called()
    assert set(_statuses(writer).values()) == {"pending"}


def test_dispatching_counts_as_activity_for_the_idle_tasks(real_db_dispatcher):
    dispatcher, _writer, lane = real_db_dispatcher

    dispatcher._dispatch_pending()

    lane.note_activity.assert_called_once_with()


def test_stale_rows_are_reset_before_the_first_dispatch(tmp_path, monkeypatch):
    import threading

    from wafer.app.indexer.dispatch import collector_dispatcher

    monkeypatch.setattr(collector_dispatcher, "_DISPATCH_INTERVAL", 0.01)
    calls = []
    writer = MagicMock()
    writer.reset_stale.side_effect = lambda names: calls.append(("reset", names))
    dispatcher = CollectorDispatcher("testdb", tmp_path / "test.db", MagicMock(), writer, MagicMock(), collectors=["exif"])
    dispatched = threading.Event()

    def dispatch():
        calls.append(("dispatch",))
        dispatched.set()

    dispatcher._dispatch_pending = dispatch
    thread = threading.Thread(target=dispatcher._dispatch_loop, daemon=True)
    thread.start()
    assert dispatched.wait(timeout=3.0)
    dispatcher._stop.set()
    dispatcher._dispatch_event.set()
    thread.join(timeout=3.0)

    assert calls[:2] == [("reset", ["exif"]), ("dispatch",)]


def test_dispatch_loop_survives_exception(tmp_path, monkeypatch):
    import threading

    from wafer.app.indexer.dispatch import collector_dispatcher

    monkeypatch.setattr(collector_dispatcher, "_DISPATCH_INTERVAL", 0.01)
    scheduler = MagicMock()
    writer = MagicMock()
    progress = MagicMock()
    db_path = tmp_path / "test.db"
    dispatcher = CollectorDispatcher("testdb", db_path, scheduler, writer, progress, collectors=["exif"])
    call_count = 0
    second_call = threading.Event()

    def failing_dispatch():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("simulated DB error")
        second_call.set()

    dispatcher._dispatch_pending = failing_dispatch
    dispatcher._stop = threading.Event()
    dispatcher._dispatch_event = threading.Event()

    thread = threading.Thread(target=dispatcher._dispatch_loop, daemon=True)
    thread.start()
    assert second_call.wait(timeout=3.0)
    dispatcher._stop.set()
    dispatcher._dispatch_event.set()
    thread.join(timeout=3.0)
    assert not thread.is_alive()


def test_per_indexer_excludes_singletons(tmp_path):
    scheduler = MagicMock()
    writer = MagicMock()
    progress = MagicMock()
    db_path = tmp_path / "test.db"
    dispatcher = CollectorDispatcher("testdb", db_path, scheduler, writer, progress)
    singleton_names = set(collector_resolver.singleton_names())
    for name in dispatcher._per_indexer:
        assert name not in singleton_names
    for name in dispatcher._collectors:
        if name not in singleton_names:
            assert name in dispatcher._per_indexer


def test_terminate_collectors_requests_shutdown_before_fallback(tmp_path):
    scheduler = MagicMock()
    writer = MagicMock()
    progress = MagicMock()
    db_path = tmp_path / "test.db"
    dispatcher = CollectorDispatcher("testdb", db_path, scheduler, writer, progress, collectors=["exif"])
    dispatcher._node = MagicMock()

    with patch.object(dispatcher, "_wait_collector_stopped", return_value=False), patch("wafer.app.indexer.dispatch.collector_dispatcher.AppProcess.terminate_cmd") as terminate_cmd:
        dispatcher._terminate_collectors()

    dispatcher._node.send.assert_called_once_with(
        "worker.shutdown",
        {"plugin": "exif"},
        dst="collector-exif",
        db="testdb",
    )
    terminate_cmd.assert_called_once_with("--collector", "testdb", "--plugin", "exif", recursive=True)


def test_terminate_collectors_skips_fallback_when_graceful_stop_succeeds(tmp_path):
    scheduler = MagicMock()
    writer = MagicMock()
    progress = MagicMock()
    db_path = tmp_path / "test.db"
    dispatcher = CollectorDispatcher("testdb", db_path, scheduler, writer, progress, collectors=["exif"])
    dispatcher._node = MagicMock()

    with patch.object(dispatcher, "_wait_collector_stopped", return_value=True), patch("wafer.app.indexer.dispatch.collector_dispatcher.AppProcess.terminate_cmd") as terminate_cmd:
        dispatcher._terminate_collectors()

    dispatcher._node.send.assert_called_once()
    terminate_cmd.assert_not_called()
