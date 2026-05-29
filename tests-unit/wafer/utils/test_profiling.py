import py_compile

import pytest

from wafer.utils.profiling import profiler


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
