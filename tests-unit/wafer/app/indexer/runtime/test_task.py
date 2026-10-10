import queue

from wafer.app.indexer.runtime.task import CancelToken, Task, TaskPriority


def test_create_factory():
    ran = []
    task = Task.create("test_op", priority=TaskPriority.REALTIME, run=lambda: ran.append(1))
    assert task.name == "test_op"
    assert task.priority == TaskPriority.REALTIME
    assert task.cancel_token is None
    assert task.on_complete is None
    task.run()
    assert ran == [1]


def test_priority_queue_ordering():
    q = queue.PriorityQueue()
    low = Task.create("purge", priority=TaskPriority.MAINTENANCE)
    high = Task.create("delete", priority=TaskPriority.REALTIME)
    q.put(low)
    q.put(high)
    first = q.get()
    second = q.get()
    assert first.priority == TaskPriority.REALTIME
    assert second.priority == TaskPriority.MAINTENANCE


def test_same_priority_fifo():
    q = queue.PriorityQueue()
    t1 = Task.create("op_a", priority=TaskPriority.SCAN)
    t2 = Task.create("op_b", priority=TaskPriority.SCAN)
    q.put(t1)
    q.put(t2)
    first = q.get()
    second = q.get()
    assert first.name == "op_a"
    assert second.name == "op_b"


def test_cancel_token_cancel():
    token = CancelToken()
    assert not token.is_cancelled
    token.cancel()
    assert token.is_cancelled
    token.cancel()
    assert token.is_cancelled
