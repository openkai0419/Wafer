from wafer.core.ipc.broker import Broker
from wafer.core.ipc.node import Node
from wafer.core.ipc.transport import NODE_QUEUE_MAX, Priority


class TestUpdateDeliveryUnderLoad:
    def _setup_pair(self):
        broker = Broker()
        broker.start()
        sender = Node("indexer", db="photos")
        sender.start(broker.port)
        sender.wait_registered(timeout=3.0)
        receiver = Node("viewer")
        receiver.start(broker.port)
        receiver.wait_registered(timeout=3.0)
        return broker, sender, receiver

    def _teardown(self, broker, *nodes):
        for n in nodes:
            n.stop()
        broker.stop()

    def test_update_after_progress_flood(self, flush_ipc):
        broker, sender, receiver = self._setup_pair()
        updates = []
        receiver.subscribe("update", lambda m: updates.append(m.payload) or True)
        try:
            for i in range(NODE_QUEUE_MAX * 2):
                sender.send_coalesced("progress", i, dst="viewer", db="photos")
            sender.send("update", "final", dst="viewer", db="photos", priority=Priority.HIGH)

            flush_ipc(sender, receiver)
            assert len(updates) >= 1, f"update message lost after {NODE_QUEUE_MAX * 2} progress messages. This demonstrates the try_put eviction issue."
        finally:
            self._teardown(broker, sender, receiver)

    def test_coalesced_update_survives_flood(self, flush_ipc):
        broker, sender, receiver = self._setup_pair()
        updates = []
        receiver.subscribe("update", lambda m: updates.append(m.payload) or True)
        try:
            for i in range(NODE_QUEUE_MAX * 2):
                sender.send_coalesced("progress", i, dst="viewer", db="photos")
            sender.send_coalesced("update", "final", dst="viewer", db="photos")

            flush_ipc(sender, receiver)
            assert len(updates) >= 1, "coalesced update should survive progress flood via broker CoalescingQueue"
        finally:
            self._teardown(broker, sender, receiver)

    def test_rapid_burst_update_delivery(self, flush_ipc):
        broker, sender, receiver = self._setup_pair()
        updates = []
        receiver.subscribe("update", lambda m: updates.append(m.payload) or True)
        try:
            for i in range(100):
                sender.send("update", i, dst="viewer", db="photos", priority=Priority.HIGH)

            flush_ipc(sender, receiver)
            assert len(updates) >= 50, f"only {len(updates)}/100 update messages delivered in rapid burst"
        finally:
            self._teardown(broker, sender, receiver)
