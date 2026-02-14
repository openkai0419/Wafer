import py_compile
import threading
import time

from source.zmq.broker import Broker, _CoalescingQueue, _PeerInfo
from source.zmq.message import Msg
from source.zmq.node import Node


def test_compile():
    py_compile.compile('source/zmq/message.py')
    py_compile.compile('source/zmq/broker.py')
    py_compile.compile('source/zmq/node.py')
    py_compile.compile('source/zmq/_core.py')


class TestMsg:

    def test_roundtrip(self):
        msg = Msg.build('db.update', {'count': 42}, src='idx-1', dst='viewer', db='photos')
        frames = msg.to_frames()
        assert len(frames) == 2
        restored = Msg.from_frames(frames)
        assert restored.topic == 'db.update'
        assert restored.src == 'idx-1'
        assert restored.dst == 'viewer'
        assert restored.db == 'photos'
        assert restored.payload == {'count': 42}
        assert restored.rid is None

    def test_roundtrip_with_rid(self):
        rid = Msg.make_rid('test-')
        msg = Msg.build('query', 'data', rid=rid)
        restored = Msg.from_frames(msg.to_frames())
        assert restored.rid == rid

    def test_reply(self):
        original = Msg.build('request', 'hello', src='a', dst='b', db='db1', rid='r1')
        reply = original.reply({'ok': True}, topic='response')
        assert reply.topic == 'response'
        assert reply.src == 'b'
        assert reply.dst == 'a'
        assert reply.db == 'db1'
        assert reply.rid == 'r1'
        assert reply.payload == {'ok': True}

    def test_from_frames_invalid(self):
        assert Msg.from_frames([b'only_one']) is None
        assert Msg.from_frames([]) is None

    def test_payload_types(self):
        for value in [42, 3.14, True, None, [1, 2], {'a': 'b'}, 'text']:
            msg = Msg.build('test', value)
            restored = Msg.from_frames(msg.to_frames())
            assert restored.payload == value


class TestCoalescingQueue:

    def test_put_and_drain(self):
        q = _CoalescingQueue(10)
        q.put('a', 1)
        q.put('b', 2)
        q.put('a', 3)
        result = q.drain()
        assert result == [('a', 3), ('b', 2)]

    def test_maxsize(self):
        q = _CoalescingQueue(2)
        q.put('a', 1)
        q.put('b', 2)
        q.put('c', 3)
        result = q.drain()
        keys = [k for k, _ in result]
        assert 'a' not in keys
        assert 'b' in keys
        assert 'c' in keys

    def test_drain_empty(self):
        q = _CoalescingQueue(10)
        assert q.drain() == []


class TestBrokerNode:

    def _make_env(self, port):
        broker = Broker(port=port)
        broker.start()
        return broker

    def test_register_and_counts(self):
        broker = Broker()
        broker.start()
        try:
            node = Node('viewer', db='photos')
            node.start(broker.port)
            assert node.wait_registered(timeout=3.0)
            assert node.viewer_id == 1
            time.sleep(0.3)
            counts = broker.get_counts()
            assert counts.get('viewer', 0) >= 1
        finally:
            node.stop()
            broker.stop()

    def test_broadcast_to_viewers(self):
        broker = Broker()
        broker.start()
        received = []
        try:
            idx = Node('collector', db='photos')
            idx.start(broker.port)
            idx.wait_registered(timeout=3.0)

            v = Node('viewer')
            v.on('db.update', lambda msg: received.append(msg))
            v.start(broker.port)
            v.wait_registered(timeout=3.0)

            idx.notify('db.update', {'count': 10})
            time.sleep(0.5)
            assert len(received) >= 1
            assert received[0].topic == 'db.update'
            assert received[0].payload == {'count': 10}
        finally:
            v.stop()
            idx.stop()
            broker.stop()

    def test_on_handler(self):
        broker = Broker()
        broker.start()
        results = []
        try:
            node = Node('collector', db='photos')
            node.on('work.assigned', lambda msg: results.append(msg.payload))
            node.start(broker.port)
            node.wait_registered(timeout=3.0)

            broker.inject(Msg.build('work.assigned', 'task1', dst='collector'))
            time.sleep(0.5)
            assert results == ['task1']
        finally:
            node.stop()
            broker.stop()

    def test_request_reply(self):
        broker = Broker()
        broker.start()
        try:
            v1 = Node('viewer', db='photos')
            v1.start(broker.port)
            v1.wait_registered(timeout=3.0)

            v2 = Node('viewer', db='photos')
            v2.start(broker.port)
            v2.wait_registered(timeout=3.0)

            reply = v1.request('mgmt.get_count', timeout=3.0)
            assert reply is not None
            assert reply.payload.get('viewer', 0) == 2
        finally:
            v2.stop()
            v1.stop()
            broker.stop()

    def test_inject(self):
        broker = Broker()
        broker.start()
        received = []
        try:
            v = Node('viewer')
            v.on('sys.notify', lambda msg: received.append(msg))
            v.start(broker.port)
            v.wait_registered(timeout=3.0)

            broker.inject(Msg.build('sys.notify', True, dst='viewer'))
            time.sleep(0.5)
            assert len(received) >= 1
            assert received[0].payload == True
        finally:
            v.stop()
            broker.stop()

    def test_db_filter(self):
        broker = Broker()
        broker.start()
        v_photos_msgs = []
        v_all_msgs = []
        try:
            idx_ill = Node('collector', db='illustrations')
            idx_ill.start(broker.port)
            idx_ill.wait_registered(timeout=3.0)

            v_photos = Node('viewer', db='photos')
            v_photos.on('db.progress', lambda m: v_photos_msgs.append(m))
            v_photos.start(broker.port)
            v_photos.wait_registered(timeout=3.0)

            v_all = Node('viewer', db=['photos', 'illustrations'])
            v_all.on('db.progress', lambda m: v_all_msgs.append(m))
            v_all.start(broker.port)
            v_all.wait_registered(timeout=3.0)

            idx_ill.notify('db.progress', 50)
            time.sleep(0.5)

            assert len(v_all_msgs) >= 1
            assert len(v_photos_msgs) == 0
        finally:
            v_all.stop()
            v_photos.stop()
            idx_ill.stop()
            broker.stop()

    def test_sender_exclusion(self):
        broker = Broker()
        broker.start()
        own_msgs = []
        try:
            node = Node('collector', db='photos')
            node.on('broadcast', lambda m: own_msgs.append(m))
            node.start(broker.port)
            node.wait_registered(timeout=3.0)

            node.send('broadcast', 'hello')
            time.sleep(0.5)
            assert len(own_msgs) == 0
        finally:
            node.stop()
            broker.stop()
