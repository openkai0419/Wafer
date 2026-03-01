import os
import subprocess
import sys
import time
import threading

import psutil
import pytest

from afterimages.core.platform.process_checker import ParentProcessChecker


class TestParentProcessChecker:

    def test_does_not_fire_while_parent_alive(self):
        fired = threading.Event()
        pc = ParentProcessChecker(os.getpid(), on_orphan=fired.set, interval=0.2)
        pc.start()
        time.sleep(0.6)
        pc.stop()
        assert not fired.is_set()

    def test_fires_when_parent_dead(self):
        proc = subprocess.Popen(
            [sys.executable, '-c', 'import time; time.sleep(60)'],
        )
        pid = proc.pid
        proc.terminate()
        proc.wait(timeout=5)

        fired = threading.Event()
        pc = ParentProcessChecker(pid, on_orphan=fired.set, interval=0.2)
        pc.start()
        assert fired.wait(timeout=3)
        pc.stop()

    def test_fires_on_pid_reuse_detection(self):
        fired = threading.Event()
        pc = ParentProcessChecker.__new__(ParentProcessChecker)
        pc._parent_pid = os.getpid()
        pc._parent_create_time = 0.0
        pc._on_orphan = fired.set
        pc._interval = 0.2
        pc._stop = threading.Event()
        pc._thread = None
        pc._fired = False
        pc.start()
        assert fired.wait(timeout=3)
        pc.stop()

    def test_stop_without_start(self):
        pc = ParentProcessChecker(os.getpid(), on_orphan=lambda: None)
        pc.stop()

    def test_callback_exception_does_not_crash(self):
        proc = subprocess.Popen(
            [sys.executable, '-c', 'import time; time.sleep(60)'],
        )
        pid = proc.pid
        proc.terminate()
        proc.wait(timeout=5)

        def bad_callback():
            raise RuntimeError('test error')

        pc = ParentProcessChecker(pid, on_orphan=bad_callback, interval=0.2)
        pc.start()
        time.sleep(1)
        pc.stop()
