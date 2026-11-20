import os
import sqlite3
import tempfile
import threading
import time
from unittest.mock import patch, MagicMock

import psutil

from wafer.core.ipc.transport import Priority
from wafer.core.ipc.message import Message
from wafer.core.ipc.node import Node
from wafer.core.ipc.outbox import (
    _SCHEMA,
    DeadOutboxCleaner,
    OutboxStore,
    owner_alive,
    _extract_pid,
    _delete_db_files,
    scan_all_outbox,
    read_outbox_of,
    remove_outbox_batch_from,
    cleanup_dead_outbox_files,
)


class TestOutboxStore:
    def _make_store(self, tmp_dir, node_id="test-node"):
        with patch("wafer.core.ipc.outbox._OUTBOX_DIR", tmp_dir):
            return OutboxStore(node_id)

    def test_push_and_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._make_store(tmp)
            rid = store.push("tag.add", {"hash": "abc", "tag": "x"}, "indexer")
            assert rid > 0
            records = store.pending()
            assert len(records) == 1
            assert records[0].topic == "tag.add"
            assert records[0].payload == {"hash": "abc", "tag": "x"}
            assert records[0].dst == "indexer"
            store.close()

    def test_remove(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._make_store(tmp)
            rid = store.push("tag.add", "data", "indexer")
            store.remove(rid)
            assert store.pending() == []
            store.close()

    def test_remove_batch(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._make_store(tmp)
            ids = [store.push("t", i, "indexer") for i in range(5)]
            store.remove_batch(ids[:3])
            remaining = store.pending()
            assert len(remaining) == 2
            store.close()

    def test_read_outbox_of_reads_only_the_named_senders(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("wafer.core.ipc.outbox._OUTBOX_DIR", tmp):
                for sender in ("sender-1", "sender-2"):
                    store = OutboxStore(sender)
                    store.push("t", sender, "indexer")
                    store.close()
                assert [r.payload for r in read_outbox_of({"sender-1"})] == ["sender-1"]

    def test_read_outbox_of_does_not_create_a_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("wafer.core.ipc.outbox._OUTBOX_DIR", tmp):
                assert read_outbox_of({"gone-1", ""}) == []
                assert os.listdir(tmp) == []

    def test_read_outbox_of_stays_in_the_outbox_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            outbox = os.path.join(tmp, "outbox")
            os.makedirs(outbox)
            with patch("wafer.core.ipc.outbox._OUTBOX_DIR", tmp):
                store = OutboxStore("outside-1")
                store.push("t", "secret", "indexer")
                store.close()
            with patch("wafer.core.ipc.outbox._OUTBOX_DIR", outbox):
                assert read_outbox_of({"../outside-1"}) == []

    def test_scan_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("wafer.core.ipc.outbox._OUTBOX_DIR", tmp):
                s1 = OutboxStore("node-a")
                s2 = OutboxStore("node-b")
                s1.push("t1", "p1", "indexer")
                s2.push("t2", "p2", "indexer")
                s1.close()
                s2.close()

                records = scan_all_outbox()
                assert len(records) == 2
                topics = {r.topic for r in records}
                assert topics == {"t1", "t2"}

    def test_scan_all_db_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("wafer.core.ipc.outbox._OUTBOX_DIR", tmp):
                store = OutboxStore("node-a")
                store.push("t1", "p1", "indexer", db="db_alpha")
                store.push("t2", "p2", "indexer", db="db_beta")
                store.push("t3", "p3", "indexer", db="")
                store.close()

                records = scan_all_outbox(db_filter="db_alpha")
                assert len(records) == 1
                assert records[0].topic == "t1"

                records = scan_all_outbox(db_filter="")
                assert len(records) == 1
                assert records[0].topic == "t3"

                records = scan_all_outbox(db_filter=None)
                assert len(records) == 3

    def test_dst_filter_combines_with_the_db_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("wafer.core.ipc.outbox._OUTBOX_DIR", tmp):
                store = OutboxStore("node-a")
                store.push("t1", "p1", "indexer", db="db_alpha")
                store.push("t2", "p2", "collector-exif", db="db_alpha")
                store.push("t3", "p3", "ALL", db="db_alpha")
                store.push("t4", "p4", "indexer", db="db_beta")
                store.close()

                records = read_outbox_of({"node-a"}, dst_filter={"indexer", "ALL"}, db_filter="db_alpha")
                assert [r.topic for r in records] == ["t1", "t3"]
                assert [r.topic for r in scan_all_outbox(dst_filter={"collector-exif"})] == ["t2"]

    def test_remove_batch_from(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("wafer.core.ipc.outbox._OUTBOX_DIR", tmp):
                store = OutboxStore("node-y")
                ids = [store.push("t", i, "indexer") for i in range(4)]
                db_path = store._path
                store.close()

                remove_outbox_batch_from(db_path, ids[:2])

                store2 = OutboxStore("node-y")
                assert len(store2.pending()) == 2
                store2.close()

    def test_a_push_that_hit_a_lock_does_not_break_later_pushes(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("wafer.core.ipc.outbox._OUTBOX_DIR", tmp):
                store = OutboxStore("indexer-1")
                try:
                    store._conn.execute("PRAGMA busy_timeout=50")
                    ids = [store.push("parse.batch", i, "parser-a") for i in range(2)]
                    consumer = sqlite3.connect(store._path)
                    consumer.execute("BEGIN IMMEDIATE")
                    try:
                        store.push("parse.batch", "blocked", "parser-b")
                        raise AssertionError("push should fail while another connection holds the write lock")
                    except sqlite3.OperationalError:
                        pass
                    finally:
                        consumer.rollback()
                        consumer.close()

                    assert store.has_pending("parse.batch", "parser-a")
                    remove_outbox_batch_from(store._path, ids)
                    assert not store.has_pending("parse.batch", "parser-a")
                    store.push("parse.batch", "after", "parser-b")
                    assert [r.payload for r in store.pending()] == ["after"]
                finally:
                    store.close()

    def test_payload_types(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._make_store(tmp)
            for val in [42, 3.14, True, None, [1, 2], {"a": "b"}, "text"]:
                store.push("test", val, "indexer")
            records = store.pending()
            payloads = [r.payload for r in records]
            assert payloads == [42, 3.14, True, None, [1, 2], {"a": "b"}, "text"]
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
            store.push("t", "data", "indexer")
            db_path = store._path
            result = store.delete_if_empty()
            assert result is False
            assert os.path.exists(db_path)
            store.close()

    def test_cleanup_empty_files_removes_dead_pid(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("wafer.core.ipc.outbox._OUTBOX_DIR", tmp):
                store = OutboxStore("viewer-99999")
                db_path = store._path
                store.close()
                assert os.path.exists(db_path)

                with patch("wafer.core.ipc.outbox.owner_alive", return_value=False):
                    cleanup_dead_outbox_files()
                assert not os.path.exists(db_path)

    @staticmethod
    def _store_with_old_row(node_id, *, days_old):
        store = OutboxStore(node_id)
        store._conn.execute(
            "INSERT INTO outbox (topic, payload, dst, db, created_at) VALUES (?, ?, ?, ?, ?)",
            ("old", b"\x90", "indexer", "gone", time.time() - 86400 * days_old),
        )
        store._conn.commit()
        store.close()
        return store._path

    def test_cleanup_drops_expired_rows_of_a_dead_sender_and_its_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("wafer.core.ipc.outbox._OUTBOX_DIR", tmp):
                db_path = self._store_with_old_row("viewer-99999", days_old=31)
                with patch("wafer.core.ipc.outbox.owner_alive", return_value=False):
                    cleanup_dead_outbox_files()
                assert not os.path.exists(db_path)

    def test_cleanup_keeps_recent_rows_of_a_dead_sender(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("wafer.core.ipc.outbox._OUTBOX_DIR", tmp):
                self._store_with_old_row("viewer-99999", days_old=29)
                with patch("wafer.core.ipc.outbox.owner_alive", return_value=False):
                    cleanup_dead_outbox_files()
                assert len(scan_all_outbox()) == 1

    def test_cleanup_leaves_a_living_sender_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("wafer.core.ipc.outbox._OUTBOX_DIR", tmp):
                self._store_with_old_row("viewer-12345", days_old=31)
                with patch("wafer.core.ipc.outbox.owner_alive", return_value=True):
                    cleanup_dead_outbox_files()
                assert len(scan_all_outbox()) == 1

    def test_cleanup_keeps_a_busy_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("wafer.core.ipc.outbox._OUTBOX_DIR", tmp):
                store = OutboxStore("viewer-99999")
                store.push("t", "data", "indexer")
                db_path = store._path
                store.close()
                with patch("wafer.core.ipc.outbox.owner_alive", return_value=False), patch("wafer.core.ipc.outbox._drop_expired_rows", side_effect=sqlite3.OperationalError("database is locked")):
                    cleanup_dead_outbox_files()
                assert os.path.exists(db_path)

    def test_cleanup_deletes_a_file_that_is_not_a_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("wafer.core.ipc.outbox._OUTBOX_DIR", tmp):
                db_path = os.path.join(tmp, "viewer-99999.db")
                with open(db_path, "wb") as f:
                    f.write(b"not a database" * 100)
                with patch("wafer.core.ipc.outbox.owner_alive", return_value=False):
                    cleanup_dead_outbox_files()
                assert not os.path.exists(db_path)

    def test_cleanup_empty_files_keeps_alive_pid(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("wafer.core.ipc.outbox._OUTBOX_DIR", tmp):
                store = OutboxStore("viewer-12345")
                db_path = store._path
                store.close()

                with patch("wafer.core.ipc.outbox.owner_alive", return_value=True):
                    cleanup_dead_outbox_files()
                assert os.path.exists(db_path)

    def test_cleanup_empty_files_keeps_nonempty(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("wafer.core.ipc.outbox._OUTBOX_DIR", tmp):
                store = OutboxStore("viewer-99999")
                store.push("t", "data", "indexer")
                db_path = store._path
                store.close()

                with patch("wafer.core.ipc.outbox.owner_alive", return_value=False):
                    cleanup_dead_outbox_files()
                assert os.path.exists(db_path)


class TestHelpers:
    def test_extract_pid(self):
        assert _extract_pid("viewer-1234") == 1234
        assert _extract_pid("collector-99999") == 99999
        assert _extract_pid("no-dash-pid") is None
        assert _extract_pid("nodash") is None
        assert _extract_pid("role-abc") is None

    def test_delete_db_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = os.path.join(tmp, "test.db")
            for suffix in ("", "-wal", "-shm"):
                with open(base + suffix, "w") as f:
                    f.write("x")
            _delete_db_files(base)
            for suffix in ("", "-wal", "-shm"):
                assert not os.path.exists(base + suffix)


class TestOwnerAlive:
    @staticmethod
    def _outbox_file(tmp, node_id):
        base = os.path.join(tmp, f"{node_id}.db")
        with open(base, "wb") as f:
            f.write(b"x")
        st = os.stat(base)
        return base, getattr(st, "st_birthtime", st.st_ctime)

    @staticmethod
    def _process_started_at(started):
        process = MagicMock()
        process.create_time.return_value = started
        return patch("wafer.core.ipc.outbox.psutil.Process", return_value=process)

    def test_the_process_that_created_the_file_is_alive(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path, created = self._outbox_file(tmp, "collector-color-4242")
            with self._process_started_at(created - 10):
                assert owner_alive(db_path)

    def test_a_pid_reused_after_the_owner_died_is_not_the_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path, created = self._outbox_file(tmp, "indexer-2208")
            with self._process_started_at(created + 10):
                assert not owner_alive(db_path)

    def test_a_reader_writing_to_a_dead_file_does_not_revive_a_reused_pid(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path, created = self._outbox_file(tmp, "indexer-2208")
            os.utime(db_path, (created + 100, created + 100))
            with self._process_started_at(created + 10):
                assert not owner_alive(db_path)

    def test_a_pid_with_no_process_is_dead(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path, _ = self._outbox_file(tmp, "viewer-4242")
            with patch("wafer.core.ipc.outbox.psutil.Process", side_effect=psutil.NoSuchProcess(4242)):
                assert not owner_alive(db_path)

    def test_a_process_it_cannot_inspect_is_left_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path, _ = self._outbox_file(tmp, "viewer-4242")
            with patch("wafer.core.ipc.outbox.psutil.Process", side_effect=psutil.AccessDenied(4242)):
                assert owner_alive(db_path)

    def test_a_name_without_a_pid_has_no_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path, _ = self._outbox_file(tmp, "tray")
            assert not owner_alive(db_path)

    def test_this_process_owns_the_outbox_it_opened(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("wafer.core.ipc.outbox._OUTBOX_DIR", tmp):
                store = OutboxStore(f"indexer-{os.getpid()}")
                try:
                    assert owner_alive(store._path)
                finally:
                    store.close()


class TestDeadOutboxCleaner:
    def test_it_cleans_at_once_and_again_after_the_interval(self):
        calls = threading.Semaphore(0)
        with patch("wafer.core.ipc.outbox.cleanup_dead_outbox_files", side_effect=lambda: calls.release()):
            cleaner = DeadOutboxCleaner(interval=0.01)
            cleaner.start()
            try:
                assert calls.acquire(timeout=5)
                assert calls.acquire(timeout=5)
            finally:
                cleaner.stop()
        assert not cleaner._thread.is_alive()

    def test_a_failed_cleanup_does_not_stop_the_next(self):
        calls = threading.Semaphore(0)

        def fail_once():
            calls.release()
            raise PermissionError("busy")

        with patch("wafer.core.ipc.outbox.cleanup_dead_outbox_files", side_effect=fail_once):
            cleaner = DeadOutboxCleaner(interval=0.01)
            cleaner.start()
            try:
                assert calls.acquire(timeout=5)
                assert calls.acquire(timeout=5)
            finally:
                cleaner.stop()

    def test_stopping_before_it_runs_again_returns_at_once(self):
        with patch("wafer.core.ipc.outbox.cleanup_dead_outbox_files"):
            cleaner = DeadOutboxCleaner(interval=3600)
            cleaner.start()
            started = time.monotonic()
            cleaner.stop()
        assert time.monotonic() - started < 5
        assert not cleaner._thread.is_alive()


class TestConsumeOutbox:
    def test_consume_deletes_on_true(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("wafer.core.ipc.outbox._OUTBOX_DIR", tmp):
                store = OutboxStore("sender-99999")
                store.push("tag.add", {"hash": "abc"}, "ALL")
                store.push("tag.remove", {"hash": "def"}, "ALL")
                store.close()

                node = Node.__new__(Node)
                node._handlers = {}
                node.node_id = "consumer-1"
                node.role = "consumer"
                node.db = ""

                received = []

                def handler(msg: Message) -> bool:
                    received.append(msg.topic)
                    return True

                node.subscribe("tag.add", handler)
                node.subscribe("tag.remove", handler)
                node._process_outbox()

                assert set(received) == {"tag.add", "tag.remove"}
                assert scan_all_outbox() == []

    def test_consume_keeps_on_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("wafer.core.ipc.outbox._OUTBOX_DIR", tmp):
                store = OutboxStore("sender-99999")
                store.push("tag.add", "data", "ALL")
                store.close()

                node = Node.__new__(Node)
                node._handlers = {}
                node.node_id = "consumer-1"
                node.role = "consumer"
                node.db = ""
                node.subscribe("tag.add", lambda msg: False)
                node._process_outbox()

                assert len(scan_all_outbox()) == 1

    def test_consume_skips_unhandled_topic(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("wafer.core.ipc.outbox._OUTBOX_DIR", tmp):
                store = OutboxStore("sender-99999")
                store.push("unknown.topic", "data", "ALL")
                store.close()

                node = Node.__new__(Node)
                node._handlers = {}
                node.node_id = "consumer-1"
                node.role = "consumer"
                node.db = ""
                node._process_outbox()

                assert len(scan_all_outbox()) == 1

    def test_consume_msg_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("wafer.core.ipc.outbox._OUTBOX_DIR", tmp):
                store = OutboxStore("sender-99999")
                store.push("tag.add", "data", "ALL")
                store.close()

                node = Node.__new__(Node)
                node._handlers = {}
                node.node_id = "consumer-1"
                node.role = "consumer"
                node.db = ""

                captured = []
                node.subscribe("tag.add", lambda msg: captured.append(msg) or True)
                node._process_outbox()

                assert captured[0].priority == Priority.MID
                assert captured[0].topic == "tag.add"
                assert captured[0].payload == "data"

    def test_consume_filters_by_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("wafer.core.ipc.outbox._OUTBOX_DIR", tmp):
                store = OutboxStore("sender-99999")
                store.push("collect.result", "mine", "indexer", db="mydb")
                store.push("collect.result", "other", "indexer", db="otherdb")
                store.close()

                node = Node.__new__(Node)
                node._handlers = {}
                node.node_id = "indexer-1"
                node.role = "indexer"
                node.db = "mydb"

                received = []
                node.subscribe("collect.result", lambda msg: received.append(msg.payload) or True)
                node._process_outbox()

                assert received == ["mine"]
                remaining = scan_all_outbox()
                assert len(remaining) == 1
                assert remaining[0].db == "otherdb"


class TestOpeningTheOutbox:
    def test_threads_sending_at_once_open_one_outbox(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("wafer.core.ipc.outbox._OUTBOX_DIR", tmp):
                opened = []
                both_inside = threading.Barrier(2, timeout=0.5)

                def open_slowly(node_id):
                    opened.append(node_id)
                    try:
                        both_inside.wait()
                    except threading.BrokenBarrierError:
                        pass
                    return OutboxStore(node_id)

                node = Node("indexer", consumer=False)
                errors = []

                def send(dst):
                    try:
                        node.send_reliable("work", dst, dst=dst)
                    except Exception as e:
                        errors.append(e)

                with patch("wafer.core.ipc.node.OutboxStore", side_effect=open_slowly):
                    threads = [threading.Thread(target=send, args=(f"worker-{i}",)) for i in range(2)]
                    for t in threads:
                        t.start()
                    for t in threads:
                        t.join()
                try:
                    assert errors == []
                    assert len(opened) == 1
                    assert sorted(r.payload for r in node._outbox.pending()) == ["worker-0", "worker-1"]
                finally:
                    node._outbox.close()

    def test_reading_another_outbox_leaves_its_journal_mode_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("wafer.core.ipc.outbox._OUTBOX_DIR", tmp):
                db_path = os.path.join(tmp, "sender-99999.db")
                conn = sqlite3.connect(db_path)
                conn.execute(_SCHEMA)
                conn.executemany(
                    "INSERT INTO outbox (topic, payload, dst, db, created_at) VALUES (?, ?, ?, ?, ?)",
                    [("t", b"\xa1x", "indexer", "", time.time()), ("t", b"\xa1y", "viewer", "", time.time())],
                )
                conn.commit()
                conn.close()

                records = read_outbox_of({"sender-99999"}, dst_filter={"indexer"})
                remove_outbox_batch_from(db_path, [r.id for r in records])
                with patch("wafer.core.ipc.outbox.owner_alive", return_value=False):
                    cleanup_dead_outbox_files()
                assert [r.payload for r in scan_all_outbox()] == ["y"]

                conn = sqlite3.connect(db_path)
                try:
                    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
                finally:
                    conn.close()


class TestNotifiedSenders:
    def _push(self, sender, payload, dst="consumer"):
        store = OutboxStore(sender)
        store.push("work", payload, dst)
        store.close()

    def test_a_notify_reads_only_the_file_of_its_sender(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("wafer.core.ipc.outbox._OUTBOX_DIR", tmp):
                self._push("noisy-1", "notified")
                self._push("silent-2", "not notified")
                received = []
                node = Node("consumer", consumer=True, outbox_poll=None)
                node.subscribe("work", lambda msg: received.append(msg.payload) or True)
                node._outbox_thread.start()
                try:
                    node._notify_outbox("noisy-1")
                    deadline = time.monotonic() + 5
                    while not received and time.monotonic() < deadline:
                        time.sleep(0.01)
                finally:
                    node.stop()
                assert received == ["notified"]
                assert [r.payload for r in scan_all_outbox()] == ["not notified"]

    def test_a_polling_consumer_still_scans_everything_under_constant_notifies(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("wafer.core.ipc.outbox._OUTBOX_DIR", tmp):
                self._push("silent-2", "left behind")
                received = threading.Event()
                node = Node("consumer", consumer=True, outbox_poll=0.05)
                node.subscribe("work", lambda msg: received.set() or True)
                node._outbox_thread.start()
                try:
                    deadline = time.monotonic() + 5
                    while not received.is_set() and time.monotonic() < deadline:
                        node._notify_outbox("noisy-1")
                        time.sleep(0.005)
                finally:
                    node.stop()
                assert received.is_set()

    def test_a_consumer_reads_a_dead_sender_but_leaves_its_file_to_the_tray(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("wafer.core.ipc.outbox._OUTBOX_DIR", tmp):
                self._push("indexer-99999", "undelivered", dst="indexer")
                received = []
                node = Node("indexer", consumer=True)
                node.subscribe("work", lambda msg: received.append(msg.payload) or True)
                with patch("wafer.core.ipc.outbox.owner_alive", return_value=False):
                    node._process_outbox()
                assert received == ["undelivered"]
                assert os.path.exists(os.path.join(tmp, "indexer-99999.db"))
