import os
import tempfile
import time
from unittest.mock import patch, MagicMock

from source.zmq._core import QoS
from source.zmq.message import Msg
from source.zmq.node import Node
from source.zmq.outbox import OutboxStore, _extract_pid, _delete_db_files


class TestOutboxStore:

    def _make_store(self, tmp_dir, node_id='test-node'):
        with patch('source.zmq.outbox._OUTBOX_DIR', tmp_dir):
            return OutboxStore(node_id)

    def test_push_and_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._make_store(tmp)
            rid = store.push('tag.add', {'hash': 'abc', 'tag': 'x'}, 'indexer')
            assert rid > 0
            records = store.pending()
            assert len(records) == 1
            assert records[0].topic == 'tag.add'
            assert records[0].payload == {'hash': 'abc', 'tag': 'x'}
            assert records[0].dst == 'indexer'
            store.close()

    def test_remove(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._make_store(tmp)
            rid = store.push('tag.add', 'data', 'indexer')
            store.remove(rid)
            assert store.pending() == []
            store.close()

    def test_remove_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._make_store(tmp)
            ids = [store.push('t', i, 'indexer') for i in range(5)]
            store.remove_batch(ids[:3])
            remaining = store.pending()
            assert len(remaining) == 2
            store.close()

    def test_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._make_store(tmp)
            store._conn.execute(
                'INSERT INTO outbox (topic, payload, dst, db, created_at) VALUES (?, ?, ?, ?, ?)',
                ('old', b'\x90', 'idx', '', time.time() - 86400 * 60),
            )
            store._conn.commit()
            store.push('new', 'data', 'indexer')
            store.cleanup(max_age_days=30)
            records = store.pending()
            assert len(records) == 1
            assert records[0].topic == 'new'
            store.close()

    def test_scan_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('source.zmq.outbox._OUTBOX_DIR', tmp):
                s1 = OutboxStore('node-a')
                s2 = OutboxStore('node-b')
                s1.push('t1', 'p1', 'indexer')
                s2.push('t2', 'p2', 'indexer')
                s1.close()
                s2.close()

                records = OutboxStore.scan_all()
                assert len(records) == 2
                topics = {r.topic for r in records}
                assert topics == {'t1', 't2'}

    def test_remove_from(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('source.zmq.outbox._OUTBOX_DIR', tmp):
                store = OutboxStore('node-x')
                rid = store.push('t', 'p', 'indexer')
                db_path = store._path
                store.close()

                OutboxStore.remove_from(db_path, rid)

                store2 = OutboxStore('node-x')
                assert store2.pending() == []
                store2.close()

    def test_remove_batch_from(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('source.zmq.outbox._OUTBOX_DIR', tmp):
                store = OutboxStore('node-y')
                ids = [store.push('t', i, 'indexer') for i in range(4)]
                db_path = store._path
                store.close()

                OutboxStore.remove_batch_from(db_path, ids[:2])

                store2 = OutboxStore('node-y')
                assert len(store2.pending()) == 2
                store2.close()

    def test_payload_types(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._make_store(tmp)
            for val in [42, 3.14, True, None, [1, 2], {'a': 'b'}, 'text']:
                store.push('test', val, 'indexer')
            records = store.pending()
            payloads = [r.payload for r in records]
            assert payloads == [42, 3.14, True, None, [1, 2], {'a': 'b'}, 'text']
            store.close()

    def test_delete_if_empty_true(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._make_store(tmp)
            db_path = store._path
            assert os.path.exists(db_path)
            result = store.delete_if_empty()
            assert result is True
            assert not os.path.exists(db_path)

    def test_delete_if_empty_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._make_store(tmp)
            store.push('t', 'data', 'indexer')
            db_path = store._path
            result = store.delete_if_empty()
            assert result is False
            assert os.path.exists(db_path)
            store.close()

    def test_cleanup_empty_files_removes_dead_pid(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('source.zmq.outbox._OUTBOX_DIR', tmp):
                store = OutboxStore('viewer-99999')
                db_path = store._path
                store.close()
                assert os.path.exists(db_path)

                with patch('source.zmq.outbox.psutil.pid_exists', return_value=False):
                    OutboxStore.cleanup_empty_files()
                assert not os.path.exists(db_path)

    def test_cleanup_empty_files_keeps_alive_pid(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('source.zmq.outbox._OUTBOX_DIR', tmp):
                store = OutboxStore('viewer-12345')
                db_path = store._path
                store.close()

                with patch('source.zmq.outbox.psutil.pid_exists', return_value=True):
                    OutboxStore.cleanup_empty_files()
                assert os.path.exists(db_path)

    def test_cleanup_empty_files_keeps_nonempty(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('source.zmq.outbox._OUTBOX_DIR', tmp):
                store = OutboxStore('viewer-99999')
                store.push('t', 'data', 'indexer')
                db_path = store._path
                store.close()

                with patch('source.zmq.outbox.psutil.pid_exists', return_value=False):
                    OutboxStore.cleanup_empty_files()
                assert os.path.exists(db_path)


class TestHelpers:

    def test_extract_pid(self):
        assert _extract_pid('viewer-1234') == 1234
        assert _extract_pid('collector-99999') == 99999
        assert _extract_pid('no-dash-pid') is None
        assert _extract_pid('nodash') is None
        assert _extract_pid('role-abc') is None

    def test_delete_db_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = os.path.join(tmp, 'test.db')
            for suffix in ('', '-wal', '-shm'):
                with open(base + suffix, 'w') as f:
                    f.write('x')
            _delete_db_files(base)
            for suffix in ('', '-wal', '-shm'):
                assert not os.path.exists(base + suffix)


class TestConsumeOutbox:

    def test_consume_deletes_on_true(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('source.zmq.outbox._OUTBOX_DIR', tmp):
                store = OutboxStore('sender-99999')
                store.push('tag.add', {'hash': 'abc'}, 'indexer')
                store.push('tag.remove', {'hash': 'def'}, 'indexer')
                store.close()

                node = Node.__new__(Node)
                node._handlers = {}

                received = []

                def handler(msg: Msg) -> bool:
                    received.append(msg.topic)
                    return True

                node.on('tag.add', handler)
                node.on('tag.remove', handler)
                node._consume_outbox()

                assert set(received) == {'tag.add', 'tag.remove'}
                assert OutboxStore.scan_all() == []

    def test_consume_keeps_on_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('source.zmq.outbox._OUTBOX_DIR', tmp):
                store = OutboxStore('sender-99999')
                store.push('tag.add', 'data', 'indexer')
                store.close()

                node = Node.__new__(Node)
                node._handlers = {}
                node.on('tag.add', lambda msg: False)
                node._consume_outbox()

                assert len(OutboxStore.scan_all()) == 1

    def test_consume_skips_unhandled_topic(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('source.zmq.outbox._OUTBOX_DIR', tmp):
                store = OutboxStore('sender-99999')
                store.push('unknown.topic', 'data', 'indexer')
                store.close()

                node = Node.__new__(Node)
                node._handlers = {}
                node._consume_outbox()

                assert len(OutboxStore.scan_all()) == 1

    def test_consume_msg_has_reliable_qos(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('source.zmq.outbox._OUTBOX_DIR', tmp):
                store = OutboxStore('sender-99999')
                store.push('tag.add', 'data', 'indexer')
                store.close()

                node = Node.__new__(Node)
                node._handlers = {}

                captured = []
                node.on('tag.add', lambda msg: captured.append(msg) or True)
                node._consume_outbox()

                assert captured[0].qos == QoS.RELIABLE
                assert captured[0].topic == 'tag.add'
                assert captured[0].payload == 'data'
