import sqlite3
from types import SimpleNamespace
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
    dispatcher = CollectorDispatcher("testdb", tmp_path / "test.db", lane, writer, MagicMock(), plugins=["exif"])
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

    from wafer.app.indexer.dispatch import plugin_dispatcher

    monkeypatch.setattr(plugin_dispatcher, "_DISPATCH_INTERVAL", 0.01)
    calls = []
    writer = MagicMock()
    writer.reset_stale.side_effect = lambda names, keep: calls.append(("reset", names)) or {}
    dispatcher = CollectorDispatcher("testdb", tmp_path / "test.db", MagicMock(), writer, MagicMock(), plugins=["exif"])
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

    from wafer.app.indexer.dispatch import plugin_dispatcher

    monkeypatch.setattr(plugin_dispatcher, "_DISPATCH_INTERVAL", 0.01)
    scheduler = MagicMock()
    writer = MagicMock()
    progress = MagicMock()
    db_path = tmp_path / "test.db"
    dispatcher = CollectorDispatcher("testdb", db_path, scheduler, writer, progress, plugins=["exif"])
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
    for name in dispatcher._plugins:
        if name not in singleton_names:
            assert name in dispatcher._per_indexer


def test_terminate_workers_requests_shutdown_before_fallback(tmp_path):
    scheduler = MagicMock()
    writer = MagicMock()
    progress = MagicMock()
    db_path = tmp_path / "test.db"
    dispatcher = CollectorDispatcher("testdb", db_path, scheduler, writer, progress, plugins=["exif"])
    dispatcher._node = MagicMock()

    with patch.object(dispatcher, "_wait_stopped", return_value=["exif"]), patch("wafer.app.indexer.dispatch.plugin_dispatcher.AppProcess.terminate_cmd") as terminate_cmd:
        dispatcher._terminate_workers()

    dispatcher._node.send.assert_called_once_with(
        "worker.shutdown",
        {"plugin": "exif"},
        dst="collector-exif",
        db="testdb",
    )
    terminate_cmd.assert_called_once_with("--collector", "testdb", "--plugin", "exif", recursive=True)


def test_terminate_workers_skips_fallback_when_graceful_stop_succeeds(tmp_path):
    scheduler = MagicMock()
    writer = MagicMock()
    progress = MagicMock()
    db_path = tmp_path / "test.db"
    dispatcher = CollectorDispatcher("testdb", db_path, scheduler, writer, progress, plugins=["exif"])
    dispatcher._node = MagicMock()

    with patch.object(dispatcher, "_wait_stopped", return_value=[]), patch("wafer.app.indexer.dispatch.plugin_dispatcher.AppProcess.terminate_cmd") as terminate_cmd:
        dispatcher._terminate_workers()

    dispatcher._node.send.assert_called_once()
    terminate_cmd.assert_not_called()


@pytest.fixture
def capped_dispatcher(tmp_path):
    from wafer.app.indexer.dispatch.plugin_dispatcher import MAX_IN_FLIGHT_BATCHES

    writer = DatabaseWriter(tmp_path / "test.db")
    writer.start()
    writer.initialize()
    sources = [f"src{i}" for i in range(MAX_IN_FLIGHT_BATCHES + 2)]
    writer.db.upsert_basic_sources([(s, f"hash-{s}", 1, 1.0) for s in sources], [])
    writer.insert_pending(sources, ["exif"])
    dispatcher = CollectorDispatcher("testdb", tmp_path / "test.db", MagicMock(), writer, MagicMock(), plugins=["exif"])
    dispatcher._node = MagicMock()
    dispatcher._node.nudge_undelivered.return_value = False
    dispatcher._read_conn = open_readonly(tmp_path / "test.db")
    with patch.object(collector_resolver, "batch_size", return_value=1):
        yield dispatcher, writer, sources, MAX_IN_FLIGHT_BATCHES
    dispatcher._read_conn.close()
    writer.close()


def test_batches_without_a_result_are_capped(capped_dispatcher):
    dispatcher, writer, sources, cap = capped_dispatcher

    for _ in sources:
        dispatcher._dispatch_pending()

    assert len(_sent_paths(dispatcher)) == cap
    assert sorted(_statuses(writer).values()) == ["dispatched"] * cap + ["pending"] * (len(sources) - cap)


def test_every_pending_row_is_sent_as_results_come_back(capped_dispatcher):
    dispatcher, _writer, sources, _cap = capped_dispatcher

    for _ in range(len(sources) * 2):
        dispatcher._dispatch_pending()
        dispatcher.batch_done("exif")

    assert sorted(p for batch in _sent_paths(dispatcher) for p in batch) == sorted(sources)


def test_reset_stale_sends_again_what_a_lost_worker_held(capped_dispatcher):
    dispatcher, writer, _sources, cap = capped_dispatcher
    for _ in range(cap + 1):
        dispatcher._dispatch_pending()
    assert len(_sent_paths(dispatcher)) == cap

    dispatcher.reset_stale()
    assert set(_statuses(writer).values()) == {"pending"}
    for _ in range(cap + 1):
        dispatcher._dispatch_pending()

    assert len(_sent_paths(dispatcher)) == cap * 2


def test_start_keeps_the_process_of_each_per_indexer_worker(tmp_path):
    per_indexer = collector_resolver.per_indexer_names()[0]
    singleton = collector_resolver.singleton_names()[0]
    dispatcher = CollectorDispatcher("testdb", tmp_path / "test.db", MagicMock(), MagicMock(), MagicMock(), plugins=[per_indexer, singleton], tray_pid=4242)
    procs = {}

    def launch(*args):
        procs[args[3]] = MagicMock()
        return procs[args[3]]

    with patch("wafer.app.indexer.dispatch.plugin_dispatcher.AppProcess.new_main", side_effect=launch) as new_main:
        dispatcher._start_workers()

    assert dispatcher._worker_procs == {per_indexer: procs[per_indexer]}
    assert new_main.call_args_list[1].args == ("--collector", "testdb", "--plugin", singleton, "--parent-pid", "4242")


@pytest.fixture
def one_by_one(real_db_dispatcher):
    dispatcher, writer, lane = real_db_dispatcher
    with patch.object(collector_resolver, "batch_size", return_value=1):
        yield dispatcher, writer, lane


@pytest.fixture
def clock(monkeypatch):
    from wafer.app.indexer.dispatch import plugin_dispatcher

    now = [1000.0]
    monkeypatch.setattr(plugin_dispatcher, "time", SimpleNamespace(monotonic=lambda: now[0]))
    return now


def _send_all_without_results(dispatcher, paused=()):
    for _ in range(3):
        dispatcher._dispatch_pending()
        sent = _sent_paths(dispatcher)[-1]
        dispatcher.batch_done("exif", [p for p in sent if p in paused])


def test_paused_rows_are_not_sent_again(one_by_one):
    dispatcher, writer, _lane = one_by_one
    _send_all_without_results(dispatcher, paused={"src1"})

    dispatcher.retry_stale()

    assert _statuses(writer) == {"src0": "pending", "src1": "dispatched", "src2": "pending"}


def test_paused_row_set_pending_again_is_sent_and_retried_like_the_others(one_by_one):
    dispatcher, writer, _lane = one_by_one
    _send_all_without_results(dispatcher, paused={"src1"})
    writer.insert_pending(["src1"], ["exif"])

    dispatcher._dispatch_pending()
    assert _sent_paths(dispatcher)[-1] == ["src1"]
    dispatcher.batch_done("exif", [])
    dispatcher.retry_stale()

    assert _statuses(writer)["src1"] == "pending"


def test_rescan_lets_paused_rows_be_sent_again(one_by_one):
    dispatcher, writer, _lane = one_by_one
    _send_all_without_results(dispatcher, paused={"src1"})

    dispatcher.resume_paused()
    dispatcher.retry_stale()

    assert set(_statuses(writer).values()) == {"pending"}


def test_sending_retried_rows_again_is_not_activity(one_by_one):
    dispatcher, _writer, lane = one_by_one
    _send_all_without_results(dispatcher)
    lane.note_activity.reset_mock()
    dispatcher._progress.increment.reset_mock()

    dispatcher.retry_stale()
    _send_all_without_results(dispatcher)

    assert len(_sent_paths(dispatcher)) == 6
    lane.note_activity.assert_not_called()
    dispatcher._progress.increment.assert_not_called()


def test_a_new_row_among_retried_ones_is_activity(one_by_one):
    dispatcher, writer, lane = one_by_one
    _send_all_without_results(dispatcher)
    dispatcher.retry_stale()
    writer.db.upsert_basic_sources([("src3", "hash-src3", 1, 1.0)], [])
    writer.insert_pending(["src3"], ["exif"])
    lane.note_activity.reset_mock()

    with patch.object(collector_resolver, "batch_size", return_value=4):
        dispatcher._dispatch_pending()

    assert sorted(_sent_paths(dispatcher)[-1]) == ["src0", "src1", "src2", "src3"]
    lane.note_activity.assert_called_once_with()
    dispatcher._progress.increment.assert_called_with(0, 4)


def test_rows_reset_at_startup_are_activity(one_by_one):
    dispatcher, _writer, lane = one_by_one
    _send_all_without_results(dispatcher)
    lane.note_activity.reset_mock()

    dispatcher.reset_stale()
    _send_all_without_results(dispatcher)

    assert lane.note_activity.call_count == 3


@pytest.mark.parametrize("in_flight", [1, 2])
def test_retry_waits_for_batches_that_may_still_be_running(one_by_one, clock, in_flight):
    dispatcher, writer, _lane = one_by_one
    for _ in range(in_flight):
        dispatcher._dispatch_pending()
    wait = in_flight * collector_resolver.batch_timeout("exif") + 60.0

    clock[0] += wait - 1
    dispatcher.retry_stale()
    assert list(_statuses(writer).values()).count("dispatched") == in_flight

    clock[0] += 1
    dispatcher.retry_stale()
    assert set(_statuses(writer).values()) == {"pending"}


def test_retry_does_not_wait_once_every_batch_came_back(one_by_one, clock):
    dispatcher, writer, _lane = one_by_one
    dispatcher._dispatch_pending()
    dispatcher.batch_done("exif", [])

    dispatcher.retry_stale()

    assert set(_statuses(writer).values()) == {"pending"}
