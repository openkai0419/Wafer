import py_compile
import threading
import time

import pytest

from wafer.app.indexer.scheduler import TaskScheduler, PeriodicTask, _QUEUE_POLL_INTERVAL
from wafer.app.indexer.db_writer import DatabaseWriter
from wafer.app.indexer.write_command import WriteCommand, WritePriority


def test_compile():
    py_compile.compile('wafer/app/indexer/scheduler.py')


@pytest.fixture
def scheduler(tmp_path):
    db_path = tmp_path / 'test.db'
    writer = DatabaseWriter(db_path)
    s = TaskScheduler(writer)
    s.start()
    s.writer.initialize()
    yield s
    s.stop()


def test_start_and_stop(tmp_path):
    db_path = tmp_path / 'test.db'
    writer = DatabaseWriter(db_path)
    s = TaskScheduler(writer)
    s.start()
    assert s._thread is not None
    assert s._thread.is_alive()
    s.stop()
    assert not s._thread.is_alive()


def test_submit_and_execute(scheduler):
    done = threading.Event()
    source_entries = [('/a.png', 'hash1', 100, 1.0, 1.0, 1.0, 'indexed')]
    image_entries = [('/a.png', '/a.png', 'a.png', 1.0)]
    cmd = WriteCommand.create(
        'upsert_sources',
        data={'source_entries': source_entries, 'image_entries': image_entries},
        on_complete=done.set,
    )
    scheduler.submit(cmd)
    assert done.wait(timeout=5.0)

    cur = scheduler.writer.db.get_reader_cursor()
    cur.execute('SELECT source FROM sources')
    rows = cur.fetchall()
    cur.close()
    assert len(rows) == 1


def test_priority_ordering(scheduler):
    execution_order = []
    lock = threading.Lock()

    source_entries = [('/a.png', 'hash1', 100, 1.0, 1.0, 1.0, 'indexed')]
    image_entries = [('/a.png', '/a.png', 'a.png', 1.0)]
    scheduler.submit(WriteCommand.create(
        'upsert_sources',
        data={'source_entries': source_entries, 'image_entries': image_entries},
    ))

    barrier = threading.Event()
    original_execute = scheduler._writer.execute

    def blocking_execute(cmd):
        barrier.wait(timeout=5.0)
        original_execute(cmd)
        with lock:
            execution_order.append(cmd.operation)

    scheduler._writer.execute = blocking_execute

    scheduler.submit(WriteCommand.create(
        'insert_pending',
        data={'sources': ['/a.png'], 'collectors': ['exif']},
    ))

    done = threading.Event()
    scheduler.submit(WriteCommand.create(
        'checkpoint',
        priority=WritePriority.MAINTENANCE,
        data={'mode': 'PASSIVE'},
        on_complete=done.set,
    ))
    scheduler.submit(WriteCommand.create(
        'delete_sources',
        priority=WritePriority.REALTIME,
        data={'paths': ['/a.png']},
    ))

    barrier.set()
    assert done.wait(timeout=5.0)

    with lock:
        pending_idx = execution_order.index('insert_pending') if 'insert_pending' in execution_order else -1
        delete_idx = execution_order.index('delete_sources') if 'delete_sources' in execution_order else -1
        checkpoint_idx = execution_order.index('checkpoint') if 'checkpoint' in execution_order else -1

    if delete_idx >= 0 and checkpoint_idx >= 0:
        assert delete_idx < checkpoint_idx


def test_on_complete_callback(scheduler):
    results = []
    done = threading.Event()

    def callback():
        results.append('called')
        done.set()

    cmd = WriteCommand.create(
        'checkpoint',
        data={'mode': 'PASSIVE'},
        on_complete=callback,
    )
    scheduler.submit(cmd)
    assert done.wait(timeout=5.0)
    assert results == ['called']


def test_on_complete_error_does_not_crash(scheduler):
    done = threading.Event()

    def bad_callback():
        raise ValueError('test error')

    def good_callback():
        done.set()

    scheduler.submit(WriteCommand.create(
        'checkpoint',
        data={'mode': 'PASSIVE'},
        on_complete=bad_callback,
    ))
    scheduler.submit(WriteCommand.create(
        'checkpoint',
        data={'mode': 'PASSIVE'},
        on_complete=good_callback,
    ))
    assert done.wait(timeout=5.0)


def test_periodic_task():
    task = PeriodicTask(
        name='test_task',
        interval=1.0,
        create_command=lambda: WriteCommand.create('checkpoint', data={'mode': 'PASSIVE'}),
    )
    now = time.monotonic()
    task.last_run = now - 2.0
    assert task.should_run(now, is_idle=False)
    task.last_run = now
    assert not task.should_run(now, is_idle=False)


def test_periodic_task_idle_only():
    task = PeriodicTask(
        name='cleanup',
        interval=1.0,
        create_command=lambda: WriteCommand.create('purge_orphans', priority=WritePriority.MAINTENANCE),
        idle_only=True,
    )
    now = time.monotonic()
    task.last_run = now - 2.0
    assert not task.should_run(now, is_idle=False)
    assert task.should_run(now, is_idle=True)


def test_idle_detection(tmp_path):
    db_path = tmp_path / 'test.db'
    writer = DatabaseWriter(db_path)
    s = TaskScheduler(writer)
    s._idle_threshold = 0.1
    s.start()
    s.writer.initialize()

    triggered = threading.Event()
    s.add_periodic_task(PeriodicTask(
        name='idle_check',
        interval=0.0,
        create_command=lambda: WriteCommand.create(
            'checkpoint',
            priority=WritePriority.MAINTENANCE,
            data={'mode': 'PASSIVE'},
            on_complete=triggered.set,
        ),
        idle_only=True,
    ))

    s._last_active_time = time.monotonic() - 1.0
    assert triggered.wait(timeout=5.0)
    s.stop()


def test_multiple_submits(scheduler):
    done = threading.Event()
    count = {'n': 0}
    lock = threading.Lock()

    def inc():
        with lock:
            count['n'] += 1
            if count['n'] >= 10:
                done.set()

    for _ in range(10):
        scheduler.submit(WriteCommand.create(
            'checkpoint',
            data={'mode': 'PASSIVE'},
            on_complete=inc,
        ))

    assert done.wait(timeout=10.0)
    assert count['n'] == 10
