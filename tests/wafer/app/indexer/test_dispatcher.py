import py_compile
from unittest.mock import MagicMock

from wafer.app.indexer.dispatcher import CollectorDispatcher, _BATCH_SIZE, _DISPATCH_INTERVAL


def test_compile():
    py_compile.compile('wafer/app/indexer/dispatcher.py')


def test_constants():
    assert _BATCH_SIZE > 0
    assert _DISPATCH_INTERVAL > 0


def test_init_with_custom_collectors(tmp_path):
    scheduler = MagicMock()
    db_path = tmp_path / 'test.db'
    dispatcher = CollectorDispatcher('testdb', db_path, scheduler, collectors=['exif', 'video'])
    assert dispatcher._collectors == ['exif', 'video']


def test_request_dispatch_sets_event(tmp_path):
    scheduler = MagicMock()
    db_path = tmp_path / 'test.db'
    dispatcher = CollectorDispatcher('testdb', db_path, scheduler, collectors=['exif'])
    assert not dispatcher._dispatch_event.is_set()
    dispatcher.request_dispatch()
    assert dispatcher._dispatch_event.is_set()


def test_reset_stale_submits_command(tmp_path):
    scheduler = MagicMock()
    db_path = tmp_path / 'test.db'
    dispatcher = CollectorDispatcher('testdb', db_path, scheduler, collectors=['exif'])
    dispatcher._reset_stale()
    assert scheduler.submit.called
    cmd = scheduler.submit.call_args[0][0]
    assert cmd.operation == 'reset_stale'
    assert cmd.data['collectors'] == ['exif']


def test_dispatched_paths_tracking(tmp_path):
    scheduler = MagicMock()
    db_path = tmp_path / 'test.db'
    dispatcher = CollectorDispatcher('testdb', db_path, scheduler, collectors=['exif'])
    dispatcher._dispatched_paths.setdefault('exif', set()).update(['a', 'b'])
    dispatcher._clear_dispatched('exif', ['a'])
    assert dispatcher._dispatched_paths['exif'] == {'b'}


def test_clear_dispatched_nonexistent_collector(tmp_path):
    scheduler = MagicMock()
    db_path = tmp_path / 'test.db'
    dispatcher = CollectorDispatcher('testdb', db_path, scheduler, collectors=['exif'])
    dispatcher._clear_dispatched('nonexistent', ['a'])
