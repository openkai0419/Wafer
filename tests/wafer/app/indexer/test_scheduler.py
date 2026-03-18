import py_compile
import threading
import time

import pytest

from wafer.app.indexer.scheduler import TaskScheduler, PeriodicTask, _QUEUE_POLL_INTERVAL
from wafer.app.indexer.task import Task, TaskPriority


def test_compile():
    py_compile.compile('wafer/app/indexer/scheduler.py')


@pytest.fixture
def scheduler():
    s = TaskScheduler()
    s.start()
    yield s
    s.stop()


def test_start_and_stop():
    s = TaskScheduler()
    s.start()
    assert s._thread is not None
    assert s._thread.is_alive()
    s.stop()
    assert not s._thread.is_alive()


def test_submit_and_execute(scheduler):
    done = threading.Event()
    results = []
    scheduler.submit(Task.create(
        'test_op',
        run=lambda: results.append('ran'),
        on_complete=done.set,
    ))
    assert done.wait(timeout=5.0)
    assert results == ['ran']


def test_priority_ordering(scheduler):
    execution_order = []
    lock = threading.Lock()
    barrier = threading.Event()

    scheduler.submit(Task.create(
        'blocker',
        priority=TaskPriority.REALTIME,
        run=lambda: barrier.wait(5.0),
    ))
    time.sleep(0.2)

    scheduler.submit(Task.create(
        'low',
        priority=TaskPriority.MAINTENANCE,
        run=lambda: (lock.acquire(), execution_order.append('low'), lock.release()),
    ))
    done = threading.Event()
    scheduler.submit(Task.create(
        'high',
        priority=TaskPriority.REALTIME,
        run=lambda: (lock.acquire(), execution_order.append('high'), lock.release()),
        on_complete=done.set,
    ))

    barrier.set()
    assert done.wait(timeout=5.0)
    time.sleep(0.3)

    with lock:
        if 'high' in execution_order and 'low' in execution_order:
            assert execution_order.index('high') < execution_order.index('low')


def test_on_complete_callback(scheduler):
    results = []
    done = threading.Event()

    scheduler.submit(Task.create(
        'op',
        run=lambda: None,
        on_complete=lambda: (results.append('called'), done.set()),
    ))
    assert done.wait(timeout=5.0)
    assert results == ['called']


def test_on_complete_error_does_not_crash(scheduler):
    done = threading.Event()

    scheduler.submit(Task.create(
        'bad_cb',
        run=lambda: None,
        on_complete=lambda: (_ for _ in ()).throw(ValueError('test error')),
    ))
    scheduler.submit(Task.create(
        'good_cb',
        run=lambda: None,
        on_complete=done.set,
    ))
    assert done.wait(timeout=5.0)


def test_cancelled_task_skipped(scheduler):
    from wafer.app.indexer.task import CancelToken
    ran = []
    done = threading.Event()

    token = CancelToken()
    token.cancel()

    scheduler.submit(Task.create(
        'cancelled_op',
        run=lambda: ran.append('should_not_run'),
        cancel_token=token,
    ))
    scheduler.submit(Task.create(
        'after',
        run=lambda: None,
        on_complete=done.set,
    ))
    assert done.wait(timeout=5.0)
    assert ran == []


def test_periodic_task():
    task = PeriodicTask(
        name='test_task',
        interval=1.0,
        create_task=lambda: Task.create('op', run=lambda: None),
    )
    now = time.monotonic()
    task.last_run = now - 2.0
    assert task.should_run(now, idle_duration=0.0)
    task.last_run = now
    assert not task.should_run(now, idle_duration=0.0)


def test_periodic_task_idle_delay():
    task = PeriodicTask(
        name='cleanup',
        interval=1.0,
        create_task=lambda: Task.create('purge', priority=TaskPriority.MAINTENANCE, run=lambda: None),
        idle_delay=300.0,
    )
    now = time.monotonic()
    task.last_run = now - 2.0
    assert not task.should_run(now, idle_duration=60.0)
    assert task.should_run(now, idle_duration=300.0)
    assert task.should_run(now, idle_duration=600.0)


def test_idle_detection():
    s = TaskScheduler()
    s.start()

    triggered = threading.Event()
    s.add_periodic_task(PeriodicTask(
        name='idle_check',
        interval=0.0,
        create_task=lambda: Task.create(
            'idle_op',
            priority=TaskPriority.MAINTENANCE,
            run=lambda: None,
            on_complete=triggered.set,
        ),
        idle_delay=0.1,
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
        scheduler.submit(Task.create(
            'op',
            run=lambda: None,
            on_complete=inc,
        ))

    assert done.wait(timeout=10.0)
    assert count['n'] == 10
