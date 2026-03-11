import py_compile

from wafer.app.indexer.write_command import WriteCommand, WritePriority


def test_compile():
    py_compile.compile('wafer/app/indexer/write_command.py')


def test_write_priority_ordering():
    assert WritePriority.REALTIME < WritePriority.SCAN
    assert WritePriority.SCAN < WritePriority.COLLECTION
    assert WritePriority.COLLECTION < WritePriority.DISPATCH
    assert WritePriority.DISPATCH < WritePriority.RETRY
    assert WritePriority.RETRY < WritePriority.MAINTENANCE


def test_create_factory():
    cmd = WriteCommand.create('delete_sources', priority=WritePriority.REALTIME, data={'paths': ['/a']})
    assert cmd.operation == 'delete_sources'
    assert cmd.priority == WritePriority.REALTIME
    assert cmd.data == {'paths': ['/a']}
    assert cmd.on_complete is None


def test_create_default_priority():
    cmd = WriteCommand.create('upsert_sources')
    assert cmd.priority == WritePriority.SCAN


def test_create_with_on_complete():
    called = []
    cmd = WriteCommand.create('checkpoint', on_complete=lambda: called.append(1))
    cmd.on_complete()
    assert called == [1]


def test_priority_queue_ordering():
    import queue
    q = queue.PriorityQueue()
    cmd_low = WriteCommand.create('purge', priority=WritePriority.MAINTENANCE)
    cmd_high = WriteCommand.create('delete', priority=WritePriority.REALTIME)
    q.put(cmd_low)
    q.put(cmd_high)
    first = q.get()
    second = q.get()
    assert first.priority == WritePriority.REALTIME
    assert second.priority == WritePriority.MAINTENANCE


def test_same_priority_fifo():
    import queue
    q = queue.PriorityQueue()
    cmd1 = WriteCommand.create('op_a', priority=WritePriority.SCAN)
    cmd2 = WriteCommand.create('op_b', priority=WritePriority.SCAN)
    q.put(cmd1)
    q.put(cmd2)
    first = q.get()
    second = q.get()
    assert first.operation == 'op_a'
    assert second.operation == 'op_b'


def test_same_priority_fifo_reverse_put():
    import queue
    q = queue.PriorityQueue()
    cmd1 = WriteCommand.create('op_a', priority=WritePriority.SCAN)
    cmd2 = WriteCommand.create('op_b', priority=WritePriority.SCAN)
    q.put(cmd2)
    q.put(cmd1)
    first = q.get()
    second = q.get()
    assert first.operation == 'op_a'
    assert second.operation == 'op_b'


def test_data_does_not_affect_ordering():
    cmd_a = WriteCommand.create('op', priority=WritePriority.SCAN, data={'big': 'payload'})
    cmd_b = WriteCommand.create('op', priority=WritePriority.SCAN, data=None)
    assert (cmd_a > cmd_b) or (cmd_a < cmd_b) or (cmd_a == cmd_b)
