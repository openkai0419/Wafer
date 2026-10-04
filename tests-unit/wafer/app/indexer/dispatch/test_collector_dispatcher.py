from unittest.mock import MagicMock, patch

from wafer.app.indexer.dispatch.collector_dispatcher import CollectorDispatcher
from wafer.plugin.collector.handler import collector_resolver


def test_reset_stale_submits_task(tmp_path):
    scheduler = MagicMock()
    writer = MagicMock()
    progress = MagicMock()
    db_path = tmp_path / "test.db"
    dispatcher = CollectorDispatcher("testdb", db_path, scheduler, writer, progress, collectors=["exif"])
    dispatcher._reset_stale()
    assert scheduler.submit.called
    task = scheduler.submit.call_args[0][0]
    assert task.name == "reset_stale"
    task.run()
    writer.reset_stale.assert_called_once_with(["exif"])


def test_dispatched_paths_tracking(tmp_path):
    scheduler = MagicMock()
    writer = MagicMock()
    progress = MagicMock()
    db_path = tmp_path / "test.db"
    dispatcher = CollectorDispatcher("testdb", db_path, scheduler, writer, progress, collectors=["exif"])
    dispatcher._dispatched_paths.setdefault("exif", set()).update(["a", "b"])
    dispatcher._clear_dispatched("exif", ["a"])
    assert dispatcher._dispatched_paths["exif"] == {"b"}


def test_clear_dispatched_nonexistent_collector(tmp_path):
    scheduler = MagicMock()
    writer = MagicMock()
    progress = MagicMock()
    db_path = tmp_path / "test.db"
    dispatcher = CollectorDispatcher("testdb", db_path, scheduler, writer, progress, collectors=["exif"])
    dispatcher._clear_dispatched("nonexistent", ["a"])


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
