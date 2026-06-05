from wafer.app.indexer.runtime.worker_shutdown import WORKER_SHUTDOWN_TIMEOUT, wait_worker_stopped


def test_worker_shutdown_timeout_is_positive():
    assert WORKER_SHUTDOWN_TIMEOUT > 0


def test_wait_worker_stopped_returns_true_when_process_absent(monkeypatch):
    from wafer.app.indexer.runtime import worker_shutdown

    calls = []

    def absent(*args):
        calls.append(args)
        return []

    monkeypatch.setattr(worker_shutdown.AppProcess, "get_by_args_subset", absent)

    assert wait_worker_stopped("parser", "testdb", "sample", timeout=0.1) is True
    assert calls == [("--parser", "testdb", "--plugin", "sample")]


def test_wait_worker_stopped_returns_false_after_timeout(monkeypatch):
    from wafer.app.indexer.runtime import worker_shutdown

    monkeypatch.setattr(worker_shutdown.AppProcess, "get_by_args_subset", lambda *args: [object()])
    monkeypatch.setattr(worker_shutdown, "WORKER_SHUTDOWN_POLL_INTERVAL", 0)

    assert wait_worker_stopped("collector", "testdb", "exif", timeout=0) is False