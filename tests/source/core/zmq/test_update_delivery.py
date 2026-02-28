import threading
import time

from source.core.zmq.broker import Broker
from source.core.zmq.node import Node
from source.core.zmq.transport import NODE_QUEUE_MAX, Priority


class TestUpdateDeliveryUnderLoad:

    def _setup_pair(self):
        broker = Broker()
        broker.start()
        sender = Node('indexer', db='photos')
        sender.start(broker.port)
        sender.wait_registered(timeout=3.0)
        receiver = Node('viewer')
        receiver.start(broker.port)
        receiver.wait_registered(timeout=3.0)
        return broker, sender, receiver

    def _teardown(self, broker, *nodes):
        for n in nodes:
            n.stop()
        broker.stop()

    def test_update_arrives_with_no_contention(self):
        broker, sender, receiver = self._setup_pair()
        received = []
        receiver.subscribe('update', lambda m: received.append(m.payload) or True)
        try:
            sender.send('update', 'v1', dst='viewer', db='photos', priority=Priority.HIGH)
            time.sleep(0.5)
            assert len(received) == 1
            assert received[0] == 'v1'
        finally:
            self._teardown(broker, sender, receiver)

    def test_update_after_progress_flood(self):
        broker, sender, receiver = self._setup_pair()
        updates = []
        receiver.subscribe('update', lambda m: updates.append(m.payload) or True)
        try:
            for i in range(NODE_QUEUE_MAX * 2):
                sender.send_coalesced('progress', i, dst='viewer', db='photos')
            sender.send('update', 'final', dst='viewer', db='photos', priority=Priority.HIGH)

            time.sleep(2.0)
            assert len(updates) >= 1, (
                f'update message lost after {NODE_QUEUE_MAX * 2} progress messages. '
                f'This demonstrates the try_put eviction issue.'
            )
        finally:
            self._teardown(broker, sender, receiver)

    def test_coalesced_update_survives_flood(self):
        broker, sender, receiver = self._setup_pair()
        updates = []
        receiver.subscribe('update', lambda m: updates.append(m.payload) or True)
        try:
            for i in range(NODE_QUEUE_MAX * 2):
                sender.send_coalesced('progress', i, dst='viewer', db='photos')
            sender.send_coalesced('update', 'final', dst='viewer', db='photos')

            time.sleep(2.0)
            assert len(updates) >= 1, (
                'coalesced update should survive progress flood via broker CoalescingQueue'
            )
        finally:
            self._teardown(broker, sender, receiver)

    def test_interleaved_progress_and_update(self):
        broker, sender, receiver = self._setup_pair()
        updates = []
        receiver.subscribe('update', lambda m: updates.append(m.payload) or True)
        try:
            for i in range(50):
                sender.send_coalesced('maximum', i * 100, dst='viewer', db='photos')
                sender.send_coalesced('progress', i * 10, dst='viewer', db='photos')
                sender.send_coalesced('update', f'batch-{i}', dst='viewer', db='photos')

            time.sleep(2.0)
            assert len(updates) >= 1
        finally:
            self._teardown(broker, sender, receiver)

    def test_rapid_burst_update_delivery(self):
        broker, sender, receiver = self._setup_pair()
        updates = []
        receiver.subscribe('update', lambda m: updates.append(m.payload) or True)
        try:
            for i in range(100):
                sender.send('update', i, dst='viewer', db='photos', priority=Priority.HIGH)

            time.sleep(2.0)
            assert len(updates) >= 50, (
                f'only {len(updates)}/100 update messages delivered in rapid burst'
            )
        finally:
            self._teardown(broker, sender, receiver)

    def test_simulated_indexer_write_cycle(self):
        broker, sender, receiver = self._setup_pair()
        updates = []
        receiver.subscribe('update', lambda m: updates.append(m.payload) or True)
        try:
            for batch_num in range(20):
                sender.send_coalesced('maximum', 1000, dst='viewer', db='photos')
                sender.send_coalesced('progress', batch_num * 50, dst='viewer', db='photos')
                sender.send_coalesced('update', f'batch-{batch_num}', dst='viewer', db='photos')
                time.sleep(0.05)

            time.sleep(2.0)
            assert len(updates) >= 1, 'at least one update notification should reach viewer'
        finally:
            self._teardown(broker, sender, receiver)
