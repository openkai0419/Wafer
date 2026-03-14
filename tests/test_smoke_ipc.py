import time

import pytest

from wafer.core.ipc.broker import Broker
from wafer.core.ipc.node import Node
from wafer.core.ipc.message import Message


def _poll_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.05)
    return predicate()


class TestSmokeIpc:

    def test_broker_node_registration(self):
        broker = Broker()
        broker.start()
        try:
            node = Node('viewer')
            node.start(port=broker.port)
            try:
                assert node.wait_registered(timeout=5.0)
                assert _poll_until(
                    lambda: broker.peer_counts().get('viewer', 0) >= 1
                )
            finally:
                node.stop()
        finally:
            broker.stop()

    def test_two_node_messaging(self):
        broker = Broker()
        broker.start()
        received = {}

        def handler(msg):
            received['msg'] = msg
            return True

        try:
            node_a = Node('viewer')
            node_b = Node('indexer', db='testdb')
            node_b.subscribe('test.ping', handler)
            node_a.start(port=broker.port)
            node_b.start(port=broker.port)
            try:
                assert node_a.wait_registered(timeout=5.0)
                assert node_b.wait_registered(timeout=5.0)
                assert _poll_until(
                    lambda: broker.peer_counts().get('viewer', 0) >= 1
                    and broker.peer_counts().get('indexer', 0) >= 1
                )
                node_a.send('test.ping', {'value': 42}, dst='indexer')
                assert _poll_until(lambda: 'msg' in received, timeout=5.0)
                assert received['msg'].payload['value'] == 42
            finally:
                node_b.stop()
                node_a.stop()
        finally:
            broker.stop()

    def test_bidirectional_messaging(self):
        broker = Broker()
        broker.start()
        received_by_a = {}
        received_by_b = {}

        def handler_a(msg):
            received_by_a['msg'] = msg
            return True

        def handler_b(msg):
            received_by_b['msg'] = msg
            return True

        try:
            node_a = Node('viewer')
            node_a.subscribe('reply.pong', handler_a)
            node_b = Node('indexer', db='testdb')
            node_b.subscribe('test.ping', handler_b)
            node_a.start(port=broker.port)
            node_b.start(port=broker.port)
            try:
                assert node_a.wait_registered(timeout=5.0)
                assert node_b.wait_registered(timeout=5.0)
                assert _poll_until(
                    lambda: broker.peer_counts().get('viewer', 0) >= 1
                    and broker.peer_counts().get('indexer', 0) >= 1
                )
                node_a.send('test.ping', {'question': 'hello'}, dst='indexer')
                assert _poll_until(lambda: 'msg' in received_by_b, timeout=5.0)
                assert received_by_b['msg'].payload['question'] == 'hello'

                node_b.send('reply.pong', {'answer': 'world'}, dst='viewer')
                assert _poll_until(lambda: 'msg' in received_by_a, timeout=5.0)
                assert received_by_a['msg'].payload['answer'] == 'world'
            finally:
                node_b.stop()
                node_a.stop()
        finally:
            broker.stop()
