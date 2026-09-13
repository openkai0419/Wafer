import py_compile

import pytest

from wafer.utils.profiling import MemoryWatchdog, profiler


@pytest.fixture(autouse=True)
def _restore_profiler_state():
    original_enabled = profiler.enabled
    original_data = {name: info.copy() for name, info in profiler.data.items()}
    profiler.data.clear()
    profiler.set_enabled(False)
    yield
    profiler.data.clear()
    profiler.data.update({name: info.copy() for name, info in original_data.items()})
    profiler.set_enabled(original_enabled)


def test_compile():
    py_compile.compile("wafer/utils/profiling.py")


def test_record_adds_named_entry():
    profiler.set_enabled(True)

    profiler.record("test.record", 0.25, self_time=0.1, count=2)

    info = profiler.data["test.record"]
    assert info["total_time"] == 0.25
    assert info["self_time"] == 0.1
    assert info["count"] == 2


def test_record_elapsed_uses_perf_counter(monkeypatch):
    profiler.set_enabled(True)
    monkeypatch.setattr("wafer.utils.profiling.time.perf_counter", lambda: 10.5)

    duration = profiler.record_elapsed("test.elapsed", 8.0)

    assert duration == 2.5
    info = profiler.data["test.elapsed"]
    assert info["total_time"] == 2.5
    assert info["self_time"] == 2.5
    assert info["count"] == 1


def test_wrap_queued_records_wait(monkeypatch):
    profiler.set_enabled(True)
    moments = iter((5.0, 8.5))
    monkeypatch.setattr("wafer.utils.profiling.time.perf_counter", lambda: next(moments))
    called = []

    wrapped = profiler.wrap_queued(lambda: called.append(True), ".post_wait")
    wrapped()

    assert called == [True]
    key = next(name for name in profiler.data if name.endswith("<lambda>.post_wait"))
    info = profiler.data[key]
    assert info["total_time"] == 3.5
    assert info["self_time"] == 3.5
    assert info["count"] == 1


class _FakeMemInfo:
    def __init__(self, rss):
        self.rss = rss


class _FakeProc:
    def __init__(self, values):
        self._values = iter(values)
        self._last = 0

    def memory_info(self):
        try:
            self._last = next(self._values)
        except StopIteration:
            pass
        return _FakeMemInfo(self._last)


def test_memwatch_report_logs_rss_and_delta(monkeypatch):
    mw = MemoryWatchdog(interval=10)
    mw._proc = _FakeProc([100 * 1024 * 1024, 130 * 1024 * 1024])
    mw._last_rss = mw._peak_rss = mw._proc.memory_info().rss
    logs = []
    monkeypatch.setattr("wafer.utils.profiling.AppLogger.info", lambda text: logs.append(text))

    mw.report()

    assert any("RSS=130.0MB" in line and "delta=+30.0MB/10s" in line for line in logs)


def test_memwatch_set_enabled_toggle():
    mw = MemoryWatchdog()
    assert mw.enabled is False
    mw.set_enabled(True)
    assert mw.enabled is True
    mw.set_enabled(False)
    assert mw.enabled is False
