import os
import tempfile
import time
from unittest.mock import patch, MagicMock

from afterimages.core.ipc.transport import Priority
from afterimages.core.ipc.message import Message
from afterimages.core.ipc.node import Node
from afterimages.core.ipc.outbox import (
    OutboxStore, _extract_pid, _delete_db_files,
    scan_all_outbox, remove_outbox_from, remove_outbox_batch_from, cleanup_empty_outbox_files,
)


class TestOutboxStore:

    def _make_store(self, tmp_dir, node_id='test-node'):
        with patch('afterimages.core.ipc.outbox._OUTBOX_DIR', tmp_dir):
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
            with patch('afterimages.core.ipc.outbox._OUTBOX_DIR', tmp):
                s1 = OutboxStore('node-a')
                s2 = OutboxStore('node-b')
                s1.push('t1', 'p1', 'indexer')
                s2.push('t2', 'p2', 'indexer')
                s1.close()
                s2.close()

                records = scan_all_outbox()
                assert len(records) == 2
                topics = {r.topic for r in records}
                assert topics == {'t1', 't2'}

    def test_scan_all_db_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('afterimages.core.ipc.outbox._OUTBOX_DIR', tmp):
                store = OutboxStore('node-a')
                store.push('t1', 'p1', 'indexer', db='db_alpha')
                store.push('t2', 'p2', 'indexer', db='db_beta')
                store.push('t3', 'p3', 'indexer', db='')
                store.close()

                records = scan_all_outbox(db_filter='db_alpha')
                assert len(records) == 1
                assert records[0].topic == 't1'

                records = scan_all_outbox(db_filter='')
                assert len(records) == 1
                assert records[0].topic == 't3'

                records = scan_all_outbox(db_filter=None)
                assert len(records) == 3

    def test_remove_from(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('afterimages.core.ipc.outbox._OUTBOX_DIR', tmp):
                store = OutboxStore('node-x')
                rid = store.push('t', 'p', 'indexer')
                db_path = store._path
                store.close()

                remove_outbox_from(db_path, rid)

                store2 = OutboxStore('node-x')
                assert store2.pending() == []
                store2.close()

    def test_remove_batch_from(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('afterimages.core.ipc.outbox._OUTBOX_DIR', tmp):
                store = OutboxStore('node-y')
                ids = [store.push('t', i, 'indexer') for i in range(4)]
                db_path = store._path
                store.close()

                remove_outbox_batch_from(db_path, ids[:2])

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
            with patch('afterimages.core.ipc.outbox._OUTBOX_DIR', tmp):
                store = OutboxStore('viewer-99999')
                db_path = store._path
                store.close()
                assert os.path.exists(db_path)

                with patch('afterimages.core.ipc.outbox.psutil.pid_exists', return_value=False):
                    cleanup_empty_outbox_files()
                assert not os.path.exists(db_path)

    def test_cleanup_empty_files_keeps_alive_pid(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('afterimages.core.ipc.outbox._OUTBOX_DIR', tmp):
                store = OutboxStore('viewer-12345')
                db_path = store._path
                store.close()

                with patch('afterimages.core.ipc.outbox.psutil.pid_exists', return_value=True):
                    cleanup_empty_outbox_files()
                assert os.path.exists(db_path)

    def test_cleanup_empty_files_keeps_nonempty(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('afterimages.core.ipc.outbox._OUTBOX_DIR', tmp):
                store = OutboxStore('viewer-99999')
                store.push('t', 'data', 'indexer')
                db_path = store._path
                store.close()

                with patch('afterimages.core.ipc.outbox.psutil.pid_exists', return_value=False):
                    cleanup_empty_outbox_files()
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
            with patch('afterimages.core.ipc.outbox._OUTBOX_DIR', tmp):
                store = OutboxStore('sender-99999')
                store.push('tag.add', {'hash': 'abc'}, 'ALL')
                store.push('tag.remove', {'hash': 'def'}, 'ALL')
                store.close()

                node = Node.__new__(Node)
                node._handlers = {}
                node.node_id = 'consumer-1'
                node.role = 'consumer'
                node.db = ''

                received = []

                def handler(msg: Message) -> bool:
                    received.append(msg.topic)
                    return True

                node.subscribe('tag.add', handler)
                node.subscribe('tag.remove', handler)
                node._process_outbox()

                assert set(received) == {'tag.add', 'tag.remove'}
                assert scan_all_outbox() == []

    def test_consume_keeps_on_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('afterimages.core.ipc.outbox._OUTBOX_DIR', tmp):
                store = OutboxStore('sender-99999')
                store.push('tag.add', 'data', 'ALL')
                store.close()

                node = Node.__new__(Node)
                node._handlers = {}
                node.node_id = 'consumer-1'
                node.role = 'consumer'
                node.db = ''
                node.subscribe('tag.add', lambda msg: False)
                node._process_outbox()

                assert len(scan_all_outbox()) == 1

    def test_consume_skips_unhandled_topic(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('afterimages.core.ipc.outbox._OUTBOX_DIR', tmp):
                store = OutboxStore('sender-99999')
                store.push('unknown.topic', 'data', 'ALL')
                store.close()

                node = Node.__new__(Node)
                node._handlers = {}
                node.node_id = 'consumer-1'
                node.role = 'consumer'
                node.db = ''
                node._process_outbox()

                assert len(scan_all_outbox()) == 1

    def test_consume_msg_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('afterimages.core.ipc.outbox._OUTBOX_DIR', tmp):
                store = OutboxStore('sender-99999')
                store.push('tag.add', 'data', 'ALL')
                store.close()

                node = Node.__new__(Node)
                node._handlers = {}
                node.node_id = 'consumer-1'
                node.role = 'consumer'
                node.db = ''

                captured = []
                node.subscribe('tag.add', lambda msg: captured.append(msg) or True)
                node._process_outbox()

                assert captured[0].priority == Priority.MID
                assert captured[0].topic == 'tag.add'
                assert captured[0].payload == 'data'

    def test_consume_filters_by_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('afterimages.core.ipc.outbox._OUTBOX_DIR', tmp):
                store = OutboxStore('sender-99999')
                store.push('collect.result', 'mine', 'indexer', db='mydb')
                store.push('collect.result', 'other', 'indexer', db='otherdb')
                store.close()

                node = Node.__new__(Node)
                node._handlers = {}
                node.node_id = 'indexer-1'
                node.role = 'indexer'
                node.db = 'mydb'

                received = []
                node.subscribe('collect.result', lambda msg: received.append(msg.payload) or True)
                node._process_outbox()

                assert received == ['mine']
                remaining = scan_all_outbox()
                assert len(remaining) == 1
                assert remaining[0].db == 'otherdb'
