import py_compile
import queue

from wafer.app.indexer.task import CancelToken, Task, TaskPriority


def test_compile():
    py_compile.compile('wafer/app/indexer/task.py')


def test_task_priority_ordering():
    assert TaskPriority.REALTIME < TaskPriority.SCAN
    assert TaskPriority.SCAN < TaskPriority.COLLECTION
    assert TaskPriority.COLLECTION < TaskPriority.DISPATCH
    assert TaskPriority.DISPATCH < TaskPriority.RETRY
    assert TaskPriority.RETRY < TaskPriority.MAINTENANCE


def test_create_factory():
    ran = []
    task = Task.create('test_op', priority=TaskPriority.REALTIME, run=lambda: ran.append(1))
    assert task.name == 'test_op'
    assert task.priority == TaskPriority.REALTIME
    assert task.cancel_token is None
    assert task.on_complete is None
    task.run()
    assert ran == [1]


def test_create_default_priority():
    task = Task.create('op')
    assert task.priority == TaskPriority.SCAN


def test_create_with_on_complete():
    called = []
    task = Task.create('op', on_complete=lambda: called.append(1))
    task.on_complete()
    assert called == [1]


def test_priority_queue_ordering():
    q = queue.PriorityQueue()
    low = Task.create('purge', priority=TaskPriority.MAINTENANCE)
    high = Task.create('delete', priority=TaskPriority.REALTIME)
    q.put(low)
    q.put(high)
    first = q.get()
    second = q.get()
    assert first.priority == TaskPriority.REALTIME
    assert second.priority == TaskPriority.MAINTENANCE


def test_same_priority_fifo():
    q = queue.PriorityQueue()
    t1 = Task.create('op_a', priority=TaskPriority.SCAN)
    t2 = Task.create('op_b', priority=TaskPriority.SCAN)
    q.put(t1)
    q.put(t2)
    first = q.get()
    second = q.get()
    assert first.name == 'op_a'
    assert second.name == 'op_b'


def test_cancel_token_initial_state():
    token = CancelToken()
    assert not token.is_cancelled


def test_cancel_token_cancel():
    token = CancelToken()
    token.cancel()
    assert token.is_cancelled


def test_cancel_token_idempotent():
    token = CancelToken()
    token.cancel()
    token.cancel()
    assert token.is_cancelled


def test_task_with_cancel_token():
    token = CancelToken()
    task = Task.create('op', cancel_token=token)
    assert task.cancel_token is token
    assert not task.cancel_token.is_cancelled
    token.cancel()
    assert task.cancel_token.is_cancelled
