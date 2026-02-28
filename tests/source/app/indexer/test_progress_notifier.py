import py_compile
import threading

from source.app.indexer.progress_notifier import ProgressAggregator


class _StubNode:
    def __init__(self):
        self.sent = []

    def send(self, *a, **kw):
        self.sent.append(('send', a, kw))

    def send_coalesced(self, *a, **kw):
        self.sent.append(('send_coalesced', a, kw))


def test_compile():
    py_compile.compile('source/app/indexer/progress_notifier.py')


def test_add_increments():
    p = ProgressAggregator('db', _StubNode())
    p.increment(0, 10)
    assert p.maximum == 10
    assert p.current == 0
    p.increment(3, 0)
    assert p.current == 3
    assert p.maximum == 10


def test_auto_reset_on_completion():
    p = ProgressAggregator('db', _StubNode())
    p.increment(0, 5)
    p.increment(5, 0)
    assert p.current == 0
    assert p.maximum == 0


def test_explicit_reset():
    p = ProgressAggregator('db', _StubNode())
    p.increment(0, 10)
    p.increment(7, 0)
    p.reset()
    assert p.current == 0
    assert p.maximum == 0


def test_add_both_at_once():
    p = ProgressAggregator('db', _StubNode())
    p.increment(3, 10)
    assert p.current == 3
    assert p.maximum == 10


def test_no_send_when_unchanged():
    node = _StubNode()
    p = ProgressAggregator('db', node)
    p.increment(0, 0)
    assert len(node.sent) == 0


def test_send_on_change():
    node = _StubNode()
    p = ProgressAggregator('db', node)
    p.increment(0, 5)
    assert len(node.sent) == 2


def test_thread_safety():
    p = ProgressAggregator('db', _StubNode())
    n = 1000
    barrier = threading.Barrier(2)
    p.increment(0, n * 2 + 1)

    def adder():
        barrier.wait()
        for _ in range(n):
            p.increment(1, 0)

    t1 = threading.Thread(target=adder)
    t2 = threading.Thread(target=adder)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert p.current == n * 2
    assert p.maximum == n * 2 + 1


def test_accumulation_across_phases():
    p = ProgressAggregator('db', _StubNode())
    p.increment(0, 10)
    p.increment(5, 5)
    assert p.current == 5
    assert p.maximum == 15
    p.increment(10, 0)
    assert p.current == 0
    assert p.maximum == 0


def test_no_reset_when_incomplete():
    p = ProgressAggregator('db', _StubNode())
    p.increment(0, 10)
    p.increment(9, 0)
    assert p.current == 9
    assert p.maximum == 10


def test_send_event_uses_coalesced():
    node = _StubNode()
    p = ProgressAggregator('testdb', node)
    p.send_event('update')
    assert len(node.sent) == 1
    method, args, kwargs = node.sent[0]
    assert method == 'send_coalesced'
    assert args == ('update', '')
    assert kwargs['dst'] == 'viewer'
    assert kwargs['db'] == 'testdb'


def test_send_event_folderchanged_uses_coalesced():
    node = _StubNode()
    p = ProgressAggregator('testdb', node)
    p.send_event('folderchanged')
    assert len(node.sent) == 1
    method, args, kwargs = node.sent[0]
    assert method == 'send_coalesced'
