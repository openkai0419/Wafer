from datetime import UTC, datetime
from types import SimpleNamespace

from wafer.app.indexer.receivers import _batch_utils
from wafer.app.indexer.receivers._batch_utils import (
    ResultBuffer,
    try_float,
    try_parse_datetime,
)


def test_try_float_numeric():
    assert try_float(None) is None
    assert try_float(42) == 42.0
    assert try_float(3.14) == 3.14
    assert try_float("123.456") == 123.456
    assert try_float("100") == 100.0


def test_try_float_rejects_non_numeric():
    assert try_float("hello") is None
    assert try_float("") is None
    assert try_float("not-a-date") is None
    assert try_parse_datetime("not-a-date") is None


def test_try_float_parses_datetime_formats():
    cases = {
        "2024:01:15 10:30:45": datetime(2024, 1, 15, 10, 30, 45, tzinfo=UTC),
        "2024-01-15 10:30:45": datetime(2024, 1, 15, 10, 30, 45, tzinfo=UTC),
        "2024:06:01": datetime(2024, 6, 1, tzinfo=UTC),
        "2024-06-01": datetime(2024, 6, 1, tzinfo=UTC),
    }
    for text, expected in cases.items():
        assert try_parse_datetime(text) == expected.timestamp()
        assert try_float(text) == expected.timestamp()


def test_result_buffer_append_drain():
    def merge(entries):
        merged = {"items": []}
        for e in entries:
            merged["items"].extend(e["items"])
        return merged

    buf = ResultBuffer(merge)
    assert buf.append({"items": [1, 2]}, 2) is True
    assert buf.append({"items": [3]}, 1) is False
    data, count = buf.drain()
    assert count == 3
    assert data["items"] == [1, 2, 3]


def test_result_buffer_empty_drain():
    buf = ResultBuffer(lambda x: {})
    data, count = buf.drain()
    assert data is None
    assert count == 0


def test_result_buffer_has_pending():
    buf = ResultBuffer(lambda x: {})
    assert buf.has_pending() is False
    buf.append({"x": 1}, 1)
    buf.drain()
    assert buf.has_pending() is False
    buf.append({"x": 1}, 1)
    with buf._lock:
        buf._flush_scheduled = False
    assert buf.has_pending() is True


def test_result_buffer_time_since_first(monkeypatch):
    clock = {"now": 100.0}
    monkeypatch.setattr(_batch_utils, "time", SimpleNamespace(monotonic=lambda: clock["now"]))
    buf = ResultBuffer(lambda x: {})
    assert buf.time_since_first() == 0.0
    buf.append({"x": 1}, 1)
    clock["now"] = 100.5
    assert buf.time_since_first() == 0.5
