from wafer.app.indexer.runtime.worker_shutdown import wait_worker_stopped


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


def _sleeper(seconds):
    import subprocess
    import sys

    return subprocess.Popen([sys.executable, "-c", f"import time; time.sleep({seconds})"])


def test_workers_are_waited_by_pid_together_without_scanning(monkeypatch):
    import time

    from wafer.app.indexer.runtime import worker_shutdown

    scans = []
    monkeypatch.setattr(worker_shutdown.AppProcess, "get_by_args_subset", lambda *args: scans.append(args) or [])
    procs = {"a": _sleeper(0.5), "b": _sleeper(0.5)}
    begin = time.monotonic()

    still_running = worker_shutdown.wait_workers_stopped("collector", "testdb", procs, timeout=10)

    assert still_running == []
    assert time.monotonic() - begin < 5
    assert scans == []


def test_worker_still_running_after_the_timeout_is_returned():
    from wafer.app.indexer.runtime.worker_shutdown import wait_workers_stopped

    slow = _sleeper(30)
    try:
        assert wait_workers_stopped("collector", "testdb", {"slow": slow}, timeout=0.2) == ["slow"]
    finally:
        slow.kill()
        slow.wait()


def test_worker_whose_process_exited_before_the_stop_is_found_by_scanning(monkeypatch):
    from wafer.app.indexer.runtime import worker_shutdown

    exited = _sleeper(0)
    exited.wait()
    scans = []
    monkeypatch.setattr(worker_shutdown.AppProcess, "get_by_args_subset", lambda *args: scans.append(args) or [])

    assert worker_shutdown.wait_workers_stopped("parser", "testdb", {"sample": exited}, timeout=1) == []
    assert scans == [("--parser", "testdb", "--plugin", "sample")]
