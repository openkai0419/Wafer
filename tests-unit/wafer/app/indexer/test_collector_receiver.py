import py_compile
import time
from unittest.mock import MagicMock

from wafer.app.indexer.collector_receiver import (
    CollectorReceiver,
    _parse_batch,
    _merge_parsed,
    _write_batched,
)
from wafer.app.indexer._parse_utils import (
    BATCH_SIZE,
    FLUSH_DELAY,
    ResultBuffer,
    try_float,
)
from wafer.utils.virtual_paths import build_virtual_path


class _StubMsg:
    def __init__(self, payload):
        self.payload = payload


def test_compile():
    py_compile.compile("wafer/app/indexer/collector_receiver.py")


def _make_receiver():
    scheduler = MagicMock()
    writer = MagicMock()
    progress = MagicMock()
    receiver = CollectorReceiver(scheduler, writer, progress)
    return receiver, scheduler, writer, progress


def test_handle_result_returns_true():
    receiver, _, _, _ = _make_receiver()
    msg = _StubMsg({"collector": "exif", "results": [{"source": "a", "status": True}]})
    assert receiver.handle_result(msg) is True


def test_handle_result_invalid_payload():
    receiver, scheduler, _, _ = _make_receiver()
    msg = _StubMsg("not_a_dict")
    assert receiver.handle_result(msg) is True
    assert not scheduler.submit.called


def test_handle_result_submits_flush_task():
    receiver, scheduler, _, _ = _make_receiver()
    results = [{"source": f"p{i}", "status": True} for i in range(5)]
    msg = _StubMsg({"collector": "exif", "results": results})
    receiver.handle_result(msg)
    assert scheduler.submit.called
    task = scheduler.submit.call_args[0][0]
    assert task.name == "flush_collection_results"


def test_handle_result_empty_results():
    receiver, scheduler, _, _ = _make_receiver()
    msg = _StubMsg({"collector": "exif", "results": []})
    receiver.handle_result(msg)
    assert not scheduler.submit.called


def test_handle_result_sets_collector_on_results():
    receiver, scheduler, writer, _ = _make_receiver()
    results = [{"source": "a", "status": True}]
    msg = _StubMsg({"collector": "test_coll", "results": results})
    receiver.handle_result(msg)
    task = scheduler.submit.call_args[0][0]
    task.run()
    call_args = writer.upsert_results.call_args
    collector_status = call_args[0][3]
    assert any(c[1] == "test_coll" for c in collector_status)


def test_coalescing_multiple_batches():
    receiver, scheduler, writer, progress = _make_receiver()
    for i in range(5):
        msg = _StubMsg(
            {
                "collector": "exif",
                "results": [{"source": f"p{i}_{j}", "status": True} for j in range(10)],
            }
        )
        receiver.handle_result(msg)
    assert scheduler.submit.call_count == 1
    task = scheduler.submit.call_args[0][0]
    task.run()
    assert writer.upsert_results.called
    cs_args = writer.upsert_results.call_args[0][3]
    assert len(cs_args) == 50
    progress.increment.assert_called_once_with(50, 0)
    progress.send_event.assert_called_once_with("update")


def test_flush_reschedules_on_pending():
    receiver, scheduler, writer, progress = _make_receiver()
    msg = _StubMsg({"collector": "exif", "results": [{"source": "a", "status": True}]})
    receiver.handle_result(msg)
    original_task = scheduler.submit.call_args[0][0]

    def add_during_flush():
        writer.upsert_results.side_effect = None
        msg2 = _StubMsg({"collector": "exif", "results": [{"source": "b", "status": True}]})
        receiver.handle_result(msg2)

    writer.upsert_results.side_effect = lambda *a: add_during_flush()
    original_task.run()
    assert scheduler.submit.call_count == 2
    second_task = scheduler.submit.call_args_list[1][0][0]
    assert second_task.name == "flush_collection_results"


def test_result_buffer_append_drain():
    buf = ResultBuffer(_merge_parsed)
    parsed = {
        "image_entries": [("p", "s", 1.0)],
        "meta_info_entries": [],
        "tag_entries": [],
        "collector_status": [("s", "exif", "ok", 0.0)],
    }
    assert buf.append(parsed, 1) is True
    assert buf.append(parsed, 1) is False
    data, count = buf.drain()
    assert count == 2
    assert len(data["collector_status"]) == 1


def test_result_buffer_empty_drain():
    buf = ResultBuffer(_merge_parsed)
    data, count = buf.drain()
    assert data is None
    assert count == 0


def test_result_buffer_has_pending():
    buf = ResultBuffer(_merge_parsed)
    assert buf.has_pending() is False
    parsed = {
        "image_entries": [],
        "meta_info_entries": [],
        "tag_entries": [],
        "collector_status": [("s", "c", "ok", 0.0)],
    }
    buf.append(parsed, 1)
    buf.drain()
    assert buf.has_pending() is False
    buf.append(parsed, 1)
    with buf._lock:
        buf._flush_scheduled = False
    assert buf.has_pending() is True


def test_merge_parsed_ok_overrides_fail():
    entries = [
        {
            "image_entries": [],
            "meta_info_entries": [],
            "tag_entries": [],
            "collector_status": [("src", "exif", "fail", 1.0)],
        },
        {
            "image_entries": [],
            "meta_info_entries": [],
            "tag_entries": [],
            "collector_status": [("src", "exif", "ok", 2.0)],
        },
    ]
    merged = _merge_parsed(entries)
    assert merged["collector_status"][0][2] == "ok"


def test_write_batched_runs_source_extension_cleanup_after_chunks():
    writer = MagicMock()
    image_entries = [(f"p{i}", "src", 1.0, "zip") for i in range(BATCH_SIZE + 1)]
    collector_status = [("src", "zip", "ok", 1.0)]
    data = {
        "image_entries": image_entries,
        "meta_info_entries": [],
        "tag_entries": [],
        "collector_status": collector_status,
    }
    _write_batched(writer, data)
    assert writer.upsert_results.call_count == 2
    assert all(call.kwargs == {"cleanup": False} for call in writer.upsert_results.call_args_list)
    writer.cleanup_source_extensions.assert_called_once_with(image_entries, collector_status)


def test_flush_delay_constant():
    assert FLUSH_DELAY > 0


def test_parse_batch_ok_status():
    results = [
        {
            "source": "src1",
            "path": "src1",
            "name": "test.png",
            "aspect": 1.5,
            "file_hash": "h1",
            "meta_info": {"width": "100"},
            "tags": {"rating": "5"},
            "status": True,
            "collector": "exif",
        }
    ]
    data = _parse_batch(results)
    assert len(data["image_entries"]) == 1
    assert data["image_entries"][0][2] == "test.png"
    assert data["image_entries"][0][3] == 1.5
    assert data["image_entries"][0][4] is None
    meta_keys = [e[1] for e in data["meta_info_entries"]]
    assert "exif.width" in meta_keys
    assert len(data["tag_entries"]) == 1
    assert len(data["collector_status"]) == 1


def test_parse_batch_fail_status():
    results = [{"source": "fail_src", "status": False, "collector": "exif"}]
    data = _parse_batch(results)
    assert data["collector_status"][0][2] == "fail"
    assert data["image_entries"] == []
    assert data["meta_info_entries"] == []
    assert data["tag_entries"] == []


def test_parse_batch_skips_none_meta():
    results = [
        {
            "source": "src",
            "file_hash": "h",
            "meta_info": {"width": "100", "empty": None},
            "tags": {"good": "yes", "bad": None},
            "status": True,
            "collector": "exif",
        }
    ]
    data = _parse_batch(results)
    meta_keys = [e[1] for e in data["meta_info_entries"]]
    assert "exif.width" in meta_keys
    assert "exif.empty" not in meta_keys
    tag_keys = [e[1] for e in data["tag_entries"]]
    assert "exif.good" in tag_keys
    assert "exif.bad" not in tag_keys


def test_parse_batch_multi_path():
    child_a = build_virtual_path("zip.zip", "a.png")
    child_b = build_virtual_path("zip.zip", "b.png")
    results = [
        {"source": "zip.zip", "path": child_a, "name": "a.png", "aspect": 0.75, "size": 10, "modified": 1.5, "status": True, "collector": "zip"},
        {"source": "zip.zip", "path": child_b, "name": "b.png", "aspect": 1.5, "size": 20, "modified": 2.5, "status": True, "collector": "zip"},
    ]
    data = _parse_batch(results)
    assert len(data["image_entries"]) == 2
    assert all(entry[4] == "zip" for entry in data["image_entries"])
    meta = {(path, key): value for path, key, value, _ in data["meta_info_entries"]}
    assert (child_a, "zip.size") not in meta
    assert (child_a, "zip.modified") not in meta
    assert (child_b, "zip.size") not in meta


def test_parse_batch_ok_overrides_fail():
    results = [
        {"source": "src", "status": False, "collector": "exif"},
        {"source": "src", "name": "ok.png", "status": True, "collector": "exif"},
    ]
    data = _parse_batch(results)
    assert data["collector_status"][0][2] == "ok"


def test_batch_size_positive():
    assert BATCH_SIZE > 0


def test_try_float_none():
    assert try_float(None) is None


def test_try_float_int():
    assert try_float(42) == 42.0


def test_try_float_float():
    assert try_float(3.14) == 3.14


def test_try_float_numeric_string():
    assert try_float("123.456") == 123.456


def test_try_float_non_numeric_string():
    assert try_float("hello") is None


def test_try_float_exif_datetime():
    result = try_float("2024:01:15 10:30:45")
    assert isinstance(result, float)
    assert result > 0
    from datetime import datetime, timezone

    expected = datetime(2024, 1, 15, 10, 30, 45, tzinfo=timezone.utc).timestamp()
    assert result == expected


def test_try_float_iso_datetime():
    result = try_float("2024-01-15 10:30:45")
    assert isinstance(result, float)
    from datetime import datetime, timezone

    expected = datetime(2024, 1, 15, 10, 30, 45, tzinfo=timezone.utc).timestamp()
    assert result == expected


def test_try_float_date_only_colon():
    result = try_float("2024:06:01")
    assert isinstance(result, float)
    from datetime import datetime, timezone

    expected = datetime(2024, 6, 1, tzinfo=timezone.utc).timestamp()
    assert result == expected


def test_try_float_date_only_hyphen():
    result = try_float("2024-06-01")
    assert isinstance(result, float)
    from datetime import datetime, timezone

    expected = datetime(2024, 6, 1, tzinfo=timezone.utc).timestamp()
    assert result == expected


def test_try_float_invalid_date():
    assert try_float("not-a-date") is None


def test_try_float_empty_string():
    assert try_float("") is None


def test_try_float_preserves_existing_numeric():
    assert try_float("100") == 100.0
    assert try_float("3.14") == 3.14


def test_parse_batch_tags_require_file_hash():
    results = [
        {
            "source": "src",
            "status": True,
            "tags": {"tags": "1girl, blue_hair"},
            "collector": "wd14",
        }
    ]
    data = _parse_batch(results)
    assert len(data["tag_entries"]) == 0


def test_parse_batch_tags_with_file_hash():
    results = [
        {
            "source": "src",
            "status": True,
            "file_hash": "abc123",
            "tags": {"tags": "1girl, blue_hair, smile"},
            "collector": "wd14",
        }
    ]
    data = _parse_batch(results)
    assert len(data["tag_entries"]) == 1
    te = data["tag_entries"][0]
    assert te[0] == "abc123"
    assert te[1] == "wd14.tags"
    assert te[2] == "1girl, blue_hair, smile"
    assert te[3] is None


def test_parse_batch_mixed_meta_and_tags():
    results = [
        {
            "source": "img.jpg",
            "status": True,
            "file_hash": "hash1",
            "meta_info": {"camera": "Canon"},
            "tags": {"tags": "landscape, sky"},
            "collector": "wd14",
        }
    ]
    data = _parse_batch(results)
    assert len(data["meta_info_entries"]) == 1
    assert len(data["tag_entries"]) == 1
    assert data["meta_info_entries"][0][1] == "wd14.camera"
    assert data["tag_entries"][0][1] == "wd14.tags"


def test_parse_batch_failed_result_no_tags():
    results = [
        {
            "source": "fail.jpg",
            "status": False,
            "file_hash": "somehash",
            "tags": {"tags": "should_not_register"},
            "collector": "wd14",
        }
    ]
    data = _parse_batch(results)
    assert len(data["tag_entries"]) == 0


def test_parse_batch_exif_datetime_value_num():
    results = [
        {
            "source": "img.jpg",
            "file_hash": "h1",
            "meta_info": {"DateTimeOriginal": "2024:01:15 10:30:45"},
            "status": True,
            "collector": "exif",
        }
    ]
    data = _parse_batch(results)
    dt_entry = [e for e in data["meta_info_entries"] if e[1] == "exif.DateTimeOriginal"]
    assert len(dt_entry) == 1
    assert dt_entry[0][2] == "2024:01:15 10:30:45"
    assert isinstance(dt_entry[0][3], float)
    assert dt_entry[0][3] > 0
