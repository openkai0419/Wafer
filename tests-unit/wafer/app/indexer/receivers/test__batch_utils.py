import py_compile
import time

from wafer.app.indexer.receivers._batch_utils import (
    BATCH_SIZE,
    FLUSH_DELAY,
    ResultBuffer,
    try_float,
    try_parse_datetime,
)


def test_compile():
    py_compile.compile("wafer/app/indexer/receivers/_batch_utils.py")


def test_constants():
    assert BATCH_SIZE > 0
    assert FLUSH_DELAY > 0


def test_try_float_none():
    assert try_float(None) is None


def test_try_float_int():
    assert try_float(42) == 42.0


def test_try_float_float():
    assert try_float(3.14) == 3.14


def test_try_float_numeric_string():
    assert try_float("123.456") == 123.456


def test_try_float_non_numeric():
    assert try_float("hello") is None


def test_try_float_empty():
    assert try_float("") is None


def test_try_float_exif_datetime():
    result = try_float("2024:01:15 10:30:45")
    assert isinstance(result, float)
    assert result > 0


def test_try_float_iso_datetime():
    result = try_float("2024-01-15 10:30:45")
    assert isinstance(result, float)


def test_try_float_date_only():
    assert isinstance(try_float("2024:06:01"), float)
    assert isinstance(try_float("2024-06-01"), float)


def test_try_parse_datetime_valid():
    result = try_parse_datetime("2024:01:15 10:30:45")
    assert isinstance(result, float)


def test_try_parse_datetime_invalid():
    assert try_parse_datetime("not-a-date") is None


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


def test_result_buffer_time_since_first():
    buf = ResultBuffer(lambda x: {})
    assert buf.time_since_first() == 0.0
    buf.append({"x": 1}, 1)
    time.sleep(0.05)
    elapsed = buf.time_since_first()
    assert elapsed >= 0.04
