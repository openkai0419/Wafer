import py_compile
import threading
import time

from source.zmq._core import QoS
from source.zmq.broker import Broker, _CoalescingQueue, _PeerInfo
from source.zmq.message import Msg
from source.zmq.node import Node


def test_compile():
    py_compile.compile('source/zmq/message.py')
    py_compile.compile('source/zmq/broker.py')
    py_compile.compile('source/zmq/node.py')
    py_compile.compile('source/zmq/_core.py')
    py_compile.compile('source/zmq/outbox.py')


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
        assert restored.qos == QoS.MID

    def test_roundtrip_with_rid(self):
        rid = Msg.make_rid('test-')
        msg = Msg.build('query', 'data', rid=rid)
        restored = Msg.from_frames(msg.to_frames())
        assert restored.rid == rid

    def test_roundtrip_with_qos(self):
        for qos_val in (QoS.LATEST, QoS.HIGH, QoS.MID, QoS.LOW, QoS.RELIABLE):
            msg = Msg.build('test', 'data', qos=qos_val)
            restored = Msg.from_frames(msg.to_frames())
            assert restored.qos == qos_val

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
            v.on('db.update', lambda msg: received.append(msg) or True)
            v.start(broker.port)
            v.wait_registered(timeout=3.0)

            idx.send('db.update', {'count': 10}, dst='viewer')
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
            node.on('work.assigned', lambda msg: results.append(msg.payload) or True)
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

            idx = Node('collector', db='photos')
            idx.start(broker.port)
            idx.wait_registered(timeout=3.0)

            reply = v1.request('mgmt.get_count', timeout=3.0)
            assert reply is not None
            assert reply.payload.get('viewer', 0) == 1
            assert reply.payload.get('collector', 0) == 1
        finally:
            idx.stop()
            v1.stop()
            broker.stop()

    def test_inject(self):
        broker = Broker()
        broker.start()
        received = []
        try:
            v = Node('viewer')
            v.on('sys.notify', lambda msg: received.append(msg) or True)
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
        v_msgs = []
        c_msgs = []
        try:
            idx_ill = Node('collector', db='illustrations')
            idx_ill.start(broker.port)
            idx_ill.wait_registered(timeout=3.0)

            v = Node('viewer', db='photos')
            v.on('db.progress', lambda m: v_msgs.append(m) or True)
            v.start(broker.port)
            v.wait_registered(timeout=3.0)

            c_all = Node('communicator', db=['photos', 'illustrations'])
            c_all.on('db.progress', lambda m: c_msgs.append(m) or True)
            c_all.start(broker.port)
            c_all.wait_registered(timeout=3.0)

            idx_ill.send('db.progress', 50)
            time.sleep(0.5)

            assert len(c_msgs) >= 1
            assert len(v_msgs) == 0
        finally:
            c_all.stop()
            v.stop()
            idx_ill.stop()
            broker.stop()

    def test_sender_exclusion(self):
        broker = Broker()
        broker.start()
        own_msgs = []
        try:
            node = Node('collector', db='photos')
            node.on('broadcast', lambda m: own_msgs.append(m) or True)
            node.start(broker.port)
            node.wait_registered(timeout=3.0)

            node.send('broadcast', 'hello')
            time.sleep(0.5)
            assert len(own_msgs) == 0
        finally:
            node.stop()
            broker.stop()


class TestQoSRouting:

    def test_latest_coalesces(self):
        broker = Broker()
        broker.start()
        received = []
        try:
            sender = Node('collector', db='photos')
            sender.start(broker.port)
            sender.wait_registered(timeout=3.0)

            viewer = Node('viewer')
            viewer.on('progress', lambda m: received.append(m.payload) or True)
            viewer.start(broker.port)
            viewer.wait_registered(timeout=3.0)

            for i in range(10):
                sender.latest('progress', i, dst='viewer', db='photos')
            time.sleep(0.5)

            assert len(received) >= 1
            assert received[-1] >= 5
        finally:
            viewer.stop()
            sender.stop()
            broker.stop()

    def test_send_ordered_all_delivered(self):
        broker = Broker()
        broker.start()
        received = []
        try:
            sender = Node('collector', db='photos')
            sender.start(broker.port)
            sender.wait_registered(timeout=3.0)

            viewer = Node('viewer')
            viewer.on('update', lambda m: received.append(m.payload) or True)
            viewer.start(broker.port)
            viewer.wait_registered(timeout=3.0)

            for i in range(5):
                sender.send('update', i, dst='viewer', priority=QoS.HIGH)
            time.sleep(0.5)

            assert received == [0, 1, 2, 3, 4]
        finally:
            viewer.stop()
            sender.stop()
            broker.stop()

    def test_send_low_priority(self):
        broker = Broker()
        broker.start()
        received = []
        try:
            sender = Node('collector', db='photos')
            sender.start(broker.port)
            sender.wait_registered(timeout=3.0)

            viewer = Node('viewer')
            viewer.on('dev.log', lambda m: received.append(m.payload) or True)
            viewer.start(broker.port)
            viewer.wait_registered(timeout=3.0)

            for i in range(3):
                sender.send('dev.log', {'n': i}, dst='viewer', priority=QoS.LOW)
            time.sleep(0.5)

            assert len(received) == 3
            assert [r['n'] for r in received] == [0, 1, 2]
        finally:
            viewer.stop()
            sender.stop()
            broker.stop()
