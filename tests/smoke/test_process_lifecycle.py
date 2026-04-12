import os
import signal
import subprocess
import sys
import time

import psutil
import pytest

from wafer.core.platform.process import AppProcess
from wafer.core.platform.process_checker import ParentProcessChecker
from wafer.utils.process_lock import SafeProcessLock


def _base_cmd():
    return AppProcess.base_command()


def _poll_until(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.1)
    return predicate()


def _find_procs(*args):
    return AppProcess.get_by_args_subset(*args)


class TestProcessLockLifecycle:
    def test_lock_acquire_release(self, tmp_path):
        lock = SafeProcessLock("test_lock_lifecycle")
        lock.lock_file = str(tmp_path / "test.lock")
        assert lock.acquire() is True
        assert os.path.exists(lock.lock_file)
        lock.release()

    def test_lock_blocks_duplicate(self, tmp_path):
        lock1 = SafeProcessLock("test_lock_dup")
        lock1.lock_file = str(tmp_path / "test.lock")
        assert lock1.acquire() is True

        lock2 = SafeProcessLock("test_lock_dup")
        lock2.lock_file = str(tmp_path / "test.lock")
        assert lock2.acquire() is False

        lock1.release()

    def test_lock_acquire_timeout_on_corruption(self, tmp_path):
        from wafer.utils.process_lock import _ACQUIRE_TIMEOUT

        lock_file = tmp_path / "test.lock"
        lock_file.write_text("corrupt data that is not json and not a pid")

        lock = SafeProcessLock("test_lock_corrupt")
        lock.lock_file = str(lock_file)
        result = lock.acquire()
        assert result is True
        lock.release()


class TestParentProcessChecker:
    def test_detects_parent_death(self):
        dummy = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        orphan_fired = []

        def on_orphan():
            orphan_fired.append(True)

        checker = ParentProcessChecker(dummy.pid, on_orphan=on_orphan, interval=0.5)
        checker.start()
        try:
            time.sleep(0.3)
            dummy.kill()
            dummy.wait(timeout=5)

            assert _poll_until(lambda: len(orphan_fired) > 0, timeout=5.0)
        finally:
            checker.stop()

    def test_no_fire_while_parent_alive(self):
        orphan_fired = []

        def on_orphan():
            orphan_fired.append(True)

        checker = ParentProcessChecker(os.getpid(), on_orphan=on_orphan, interval=0.5)
        checker.start()
        try:
            time.sleep(2.0)
            assert len(orphan_fired) == 0
        finally:
            checker.stop()


class TestCollectorWorkerLifecycle:
    def test_worker_starts_and_stops_cleanly(self):
        from wafer.core.ipc.broker import Broker
        from wafer.app.collector.worker import CollectorWorker

        broker = Broker()
        broker.start()
        try:
            worker = CollectorWorker("testdb", "exiftool")
            worker.start()
            try:
                assert worker._node.wait_registered(timeout=5.0)
            finally:
                worker.stop()
            assert worker._stop.is_set()
        finally:
            broker.stop()

    def test_stop_is_idempotent(self):
        from wafer.core.ipc.broker import Broker
        from wafer.app.collector.worker import CollectorWorker

        broker = Broker()
        broker.start()
        try:
            worker = CollectorWorker("testdb", "exiftool")
            worker.start()
            assert worker._node.wait_registered(timeout=5.0)
            worker.stop()
            worker.stop()
        finally:
            broker.stop()

    def test_stop_guard_rejects_new_batch(self):
        from wafer.core.ipc.broker import Broker
        from wafer.app.collector.worker import CollectorWorker
        from wafer.core.ipc.message import Message

        broker = Broker()
        broker.start()
        try:
            worker = CollectorWorker("testdb", "exiftool")
            worker.start()
            assert worker._node.wait_registered(timeout=5.0)
            worker._stop.set()
            msg = Message.build(
                "collect.batch",
                {"paths": ["/fake/path.jpg"], "file_info": {}},
                src="test",
                dst="collector-exiftool",
                db="testdb",
            )
            result = worker._handle_batch(msg)
            assert result is True
            worker.stop()
        finally:
            broker.stop()


class TestParserWorkerLifecycle:
    def test_worker_starts_and_stops_cleanly(self):
        from wafer.core.ipc.broker import Broker
        from wafer.app.parser.worker import ParserWorker
        from wafer.plugin.parser.handler import parser_resolver

        names = parser_resolver.names()
        if not names:
            pytest.skip("No parser plugins available")

        broker = Broker()
        broker.start()
        try:
            worker = ParserWorker("testdb", names[0])
            worker.start()
            try:
                assert worker._node.wait_registered(timeout=5.0)
            finally:
                worker.stop()
            assert worker._stop.is_set()
        finally:
            broker.stop()


class TestDispatcherSingletonState:
    def test_reset_singleton_state(self):
        from wafer.app.indexer.dispatcher import CollectorDispatcher
        from wafer.app.indexer.parser_dispatcher import ParserDispatcher

        CollectorDispatcher._singleton_started.add("test_plugin")
        ParserDispatcher._singleton_started.add("test_parser")

        CollectorDispatcher.reset_singleton_state()
        ParserDispatcher.reset_singleton_state()

        assert len(CollectorDispatcher._singleton_started) == 0
        assert len(ParserDispatcher._singleton_started) == 0


class TestTerminateAndWait:
    def test_terminate_and_wait_kills_process(self):
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        ps_proc = psutil.Process(proc.pid)
        assert ps_proc.is_running()

        AppProcess.terminate_and_wait([ps_proc], timeout=3, kill_timeout=2)
        assert not ps_proc.is_running()

    def test_force_kill_on_unkillable_process(self):
        code = "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(60)"
        proc = subprocess.Popen(
            [sys.executable, "-c", code],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        ps_proc = psutil.Process(proc.pid)
        assert ps_proc.is_running()

        AppProcess.terminate_and_wait([ps_proc], timeout=2, kill_timeout=2)
        assert not ps_proc.is_running()

    def test_shutdown_children_cleans_all(self):
        procs = []
        for _ in range(3):
            p = subprocess.Popen(
                [sys.executable, "-c", "import time; time.sleep(60)"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            procs.append(p)

        ps_procs = [psutil.Process(p.pid) for p in procs]
        for pp in ps_procs:
            assert pp.is_running()

        AppProcess.terminate_and_wait(ps_procs, timeout=3, kill_timeout=2)

        for pp in ps_procs:
            assert not pp.is_running()
