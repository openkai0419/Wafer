import py_compile
import time
from unittest.mock import MagicMock

from wafer.app.indexer.collector_receiver import CollectorReceiver, _parse_batch, _BATCH_SIZE, _try_float


class _StubMsg:
    def __init__(self, payload):
        self.payload = payload


def test_compile():
    py_compile.compile('wafer/app/indexer/collector_receiver.py')


def _make_receiver():
    scheduler = MagicMock()
    writer = MagicMock()
    progress = MagicMock()
    receiver = CollectorReceiver(scheduler, writer, progress)
    return receiver, scheduler, writer, progress


def test_handle_result_returns_true():
    receiver, _, _, _ = _make_receiver()
    msg = _StubMsg({'collector': 'exif', 'results': [{'source': 'a', 'status': True}]})
    assert receiver.handle_result(msg) is True


def test_handle_result_invalid_payload():
    receiver, scheduler, _, _ = _make_receiver()
    msg = _StubMsg('not_a_dict')
    assert receiver.handle_result(msg) is True
    assert not scheduler.submit.called


def test_handle_result_submits_tasks():
    receiver, scheduler, _, _ = _make_receiver()
    results = [{'source': f'p{i}', 'status': True} for i in range(5)]
    msg = _StubMsg({'collector': 'exif', 'results': results})
    receiver.handle_result(msg)
    assert scheduler.submit.called
    task = scheduler.submit.call_args[0][0]
    assert task.name == 'upsert_results'


def test_handle_result_empty_results():
    receiver, scheduler, _, _ = _make_receiver()
    msg = _StubMsg({'collector': 'exif', 'results': []})
    receiver.handle_result(msg)
    assert not scheduler.submit.called


def test_handle_result_sets_collector_on_results():
    receiver, scheduler, writer, _ = _make_receiver()
    results = [{'source': 'a', 'status': True}]
    msg = _StubMsg({'collector': 'test_coll', 'results': results})
    receiver.handle_result(msg)
    task = scheduler.submit.call_args[0][0]
    task.run()
    call_args = writer.upsert_results.call_args
    collector_status = call_args[0][3]
    assert any(c[1] == 'test_coll' for c in collector_status)


def test_parse_batch_ok_status():
    results = [{
        'source': 'src1',
        'path': 'src1',
        'name': 'test.png',
        'aspect': 1.5,
        'file_hash': 'h1',
        'meta_info': {'width': '100'},
        'tags': {'rating': '5'},
        'status': True,
        'collector': 'exif',
    }]
    data = _parse_batch(results)
    assert len(data['image_entries']) == 1
    assert data['image_entries'][0][2] == 1.5
    meta_keys = [e[1] for e in data['meta_info_entries']]
    assert 'width' in meta_keys
    assert len(data['tag_entries']) == 1
    assert len(data['collector_status']) == 1


def test_parse_batch_fail_status():
    results = [{'source': 'fail_src', 'status': False, 'collector': 'exif'}]
    data = _parse_batch(results)
    assert data['collector_status'][0][2] == 'fail'
    assert data['image_entries'] == []
    assert data['meta_info_entries'] == []
    assert data['tag_entries'] == []


def test_parse_batch_skips_none_meta():
    results = [{
        'source': 'src',
        'file_hash': 'h',
        'meta_info': {'width': '100', 'empty': None},
        'tags': {'good': 'yes', 'bad': None},
        'status': True,
        'collector': 'exif',
    }]
    data = _parse_batch(results)
    meta_keys = [e[1] for e in data['meta_info_entries']]
    assert 'width' in meta_keys
    assert 'empty' not in meta_keys
    tag_keys = [e[1] for e in data['tag_entries']]
    assert 'good' in tag_keys
    assert 'bad' not in tag_keys


def test_parse_batch_multi_path():
    results = [
        {'source': 'zip.zip', 'path': 'zip.zip::a.png', 'name': 'a.png', 'aspect': 0.75, 'status': True, 'collector': 'zip'},
        {'source': 'zip.zip', 'path': 'zip.zip::b.png', 'name': 'b.png', 'aspect': 1.5, 'status': True, 'collector': 'zip'},
    ]
    data = _parse_batch(results)
    assert len(data['image_entries']) == 2


def test_parse_batch_ok_overrides_fail():
    results = [
        {'source': 'src', 'status': False, 'collector': 'exif'},
        {'source': 'src', 'name': 'ok.png', 'status': True, 'collector': 'exif'},
    ]
    data = _parse_batch(results)
    assert data['collector_status'][0][2] == 'ok'


def test_batch_size_positive():
    assert _BATCH_SIZE > 0


def test_try_float_none():
    assert _try_float(None) is None


def test_try_float_int():
    assert _try_float(42) == 42.0


def test_try_float_float():
    assert _try_float(3.14) == 3.14


def test_try_float_numeric_string():
    assert _try_float('123.456') == 123.456


def test_try_float_non_numeric_string():
    assert _try_float('hello') is None


def test_try_float_exif_datetime():
    result = _try_float('2024:01:15 10:30:45')
    assert isinstance(result, float)
    assert result > 0
    from datetime import datetime, timezone
    expected = datetime(2024, 1, 15, 10, 30, 45, tzinfo=timezone.utc).timestamp()
    assert result == expected


def test_try_float_iso_datetime():
    result = _try_float('2024-01-15 10:30:45')
    assert isinstance(result, float)
    from datetime import datetime, timezone
    expected = datetime(2024, 1, 15, 10, 30, 45, tzinfo=timezone.utc).timestamp()
    assert result == expected


def test_try_float_date_only_colon():
    result = _try_float('2024:06:01')
    assert isinstance(result, float)
    from datetime import datetime, timezone
    expected = datetime(2024, 6, 1, tzinfo=timezone.utc).timestamp()
    assert result == expected


def test_try_float_date_only_hyphen():
    result = _try_float('2024-06-01')
    assert isinstance(result, float)
    from datetime import datetime, timezone
    expected = datetime(2024, 6, 1, tzinfo=timezone.utc).timestamp()
    assert result == expected


def test_try_float_invalid_date():
    assert _try_float('not-a-date') is None


def test_try_float_empty_string():
    assert _try_float('') is None


def test_try_float_preserves_existing_numeric():
    assert _try_float('100') == 100.0
    assert _try_float('3.14') == 3.14


def test_parse_batch_exif_datetime_value_num():
    results = [{
        'source': 'img.jpg',
        'file_hash': 'h1',
        'meta_info': {'exif.DateTimeOriginal': '2024:01:15 10:30:45'},
        'status': True,
        'collector': 'exif',
    }]
    data = _parse_batch(results)
    dt_entry = [e for e in data['meta_info_entries'] if e[1] == 'exif.DateTimeOriginal']
    assert len(dt_entry) == 1
    assert dt_entry[0][2] == '2024:01:15 10:30:45'
    assert isinstance(dt_entry[0][3], float)
    assert dt_entry[0][3] > 0
