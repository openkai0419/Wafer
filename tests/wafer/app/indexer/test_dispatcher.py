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
    writer = MagicMock()
    progress = MagicMock()
    db_path = tmp_path / 'test.db'
    dispatcher = CollectorDispatcher('testdb', db_path, scheduler, writer, progress, collectors=['exif', 'video'])
    assert dispatcher._collectors == ['exif', 'video']


def test_request_dispatch_sets_event(tmp_path):
    scheduler = MagicMock()
    writer = MagicMock()
    progress = MagicMock()
    db_path = tmp_path / 'test.db'
    dispatcher = CollectorDispatcher('testdb', db_path, scheduler, writer, progress, collectors=['exif'])
    assert not dispatcher._dispatch_event.is_set()
    dispatcher.request_dispatch()
    assert dispatcher._dispatch_event.is_set()


def test_reset_stale_submits_task(tmp_path):
    scheduler = MagicMock()
    writer = MagicMock()
    progress = MagicMock()
    db_path = tmp_path / 'test.db'
    dispatcher = CollectorDispatcher('testdb', db_path, scheduler, writer, progress, collectors=['exif'])
    dispatcher._reset_stale()
    assert scheduler.submit.called
    task = scheduler.submit.call_args[0][0]
    assert task.name == 'reset_stale'
    task.run()
    writer.reset_stale.assert_called_once_with(['exif'])


def test_dispatched_paths_tracking(tmp_path):
    scheduler = MagicMock()
    writer = MagicMock()
    progress = MagicMock()
    db_path = tmp_path / 'test.db'
    dispatcher = CollectorDispatcher('testdb', db_path, scheduler, writer, progress, collectors=['exif'])
    dispatcher._dispatched_paths.setdefault('exif', set()).update(['a', 'b'])
    dispatcher._clear_dispatched('exif', ['a'])
    assert dispatcher._dispatched_paths['exif'] == {'b'}


def test_clear_dispatched_nonexistent_collector(tmp_path):
    scheduler = MagicMock()
    writer = MagicMock()
    progress = MagicMock()
    db_path = tmp_path / 'test.db'
    dispatcher = CollectorDispatcher('testdb', db_path, scheduler, writer, progress, collectors=['exif'])
    dispatcher._clear_dispatched('nonexistent', ['a'])


def test_dispatch_loop_survives_exception(tmp_path):
    import threading
    scheduler = MagicMock()
    writer = MagicMock()
    progress = MagicMock()
    db_path = tmp_path / 'test.db'
    dispatcher = CollectorDispatcher('testdb', db_path, scheduler, writer, progress, collectors=['exif'])
    call_count = 0
    original_dispatch = dispatcher._dispatch_pending

    def failing_dispatch():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError('simulated DB error')
        original_dispatch()

    dispatcher._dispatch_pending = failing_dispatch
    dispatcher._stop = threading.Event()
    dispatcher._dispatch_event = threading.Event()

    thread = threading.Thread(target=dispatcher._dispatch_loop, daemon=True)
    thread.start()
    dispatcher._dispatch_event.set()
    import time; time.sleep(0.3)
    dispatcher._dispatch_event.set()
    time.sleep(0.3)
    dispatcher._stop.set()
    dispatcher._dispatch_event.set()
    thread.join(timeout=3.0)
    assert not thread.is_alive()
    assert call_count >= 2
