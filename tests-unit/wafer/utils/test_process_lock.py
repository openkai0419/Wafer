import json
import py_compile

import pytest


def test_compile():
    py_compile.compile("wafer/utils/process_lock.py")


def test_acquire_removes_stale_lock_when_pid_reused(tmp_path, monkeypatch):
    from wafer.utils import process_lock as process_lock_mod

    lock_path = tmp_path / "app.lock"
    lock_path.write_text(json.dumps({"pid": 123, "create_time": 1.0}), encoding="utf-8")

    class _NoSuchProcess(Exception):
        pass

    class _AccessDenied(Exception):
        pass

    class _Error(Exception):
        pass

    class _Proc:
        def __init__(self, pid):
            self._pid = pid

        def create_time(self):
            if self._pid == 123:
                return 2.0
            return 10.0

    class _Psutil:
        Error = _Error
        NoSuchProcess = _NoSuchProcess
        AccessDenied = _AccessDenied

        @staticmethod
        def Process(pid):
            return _Proc(pid)

    monkeypatch.setattr(process_lock_mod, "resolve_data_path", lambda _: str(lock_path))
    monkeypatch.setattr(process_lock_mod, "psutil", _Psutil)

    lock = process_lock_mod.SafeProcessLock("app")
    assert lock.acquire() is True
    assert json.loads(lock_path.read_text(encoding="utf-8"))["pid"] == lock.pid


def test_acquire_keeps_lock_when_same_process_identity(tmp_path, monkeypatch):
    from wafer.utils import process_lock as process_lock_mod

    lock_path = tmp_path / "app.lock"

    class _NoSuchProcess(Exception):
        pass

    class _AccessDenied(Exception):
        pass

    class _Error(Exception):
        pass

    class _Proc:
        def __init__(self, pid, ct):
            self._pid = pid
            self._ct = ct

        def create_time(self):
            return self._ct

    class _Psutil:
        Error = _Error
        NoSuchProcess = _NoSuchProcess
        AccessDenied = _AccessDenied

        _map = {}

        @classmethod
        def Process(cls, pid):
            ct = cls._map.get(pid)
            if ct is None:
                ct = 10.0
                cls._map[pid] = ct
            return _Proc(pid, ct)

    monkeypatch.setattr(process_lock_mod, "resolve_data_path", lambda _: str(lock_path))
    monkeypatch.setattr(process_lock_mod, "psutil", _Psutil)

    probe = process_lock_mod.SafeProcessLock("app")
    _Psutil._map[probe.pid] = probe.create_time
    lock_path.write_text(json.dumps({"pid": probe.pid, "create_time": probe.create_time}), encoding="utf-8")

    lock = process_lock_mod.SafeProcessLock("app")
    assert lock.acquire() is False


def test_acquire_removes_lock_when_process_disappears(tmp_path, monkeypatch):
    from wafer.utils import process_lock as process_lock_mod

    lock_path = tmp_path / "app.lock"
    lock_path.write_text(json.dumps({"pid": 321, "create_time": 1.0}), encoding="utf-8")

    class _NoSuchProcess(Exception):
        pass

    class _AccessDenied(Exception):
        pass

    class _Error(Exception):
        pass

    class _Proc:
        def __init__(self, pid):
            self._pid = pid
            self._called = False

        def create_time(self):
            if self._pid == 321 and not self._called:
                self._called = True
                raise _NoSuchProcess()
            return 10.0

    class _Psutil:
        Error = _Error
        NoSuchProcess = _NoSuchProcess
        AccessDenied = _AccessDenied

        @staticmethod
        def Process(pid):
            return _Proc(pid)

    monkeypatch.setattr(process_lock_mod, "resolve_data_path", lambda _: str(lock_path))
    monkeypatch.setattr(process_lock_mod, "psutil", _Psutil)

    lock = process_lock_mod.SafeProcessLock("app")
    assert lock.acquire() is True


class TestFileLock:
    def test_lock_creates_lock_file(self, tmp_path):
        from wafer.utils.process_lock import file_lock

        lock_path = str(tmp_path / "test.lock")
        with file_lock(lock_path):
            import os

            assert os.path.exists(lock_path)

    def test_lock_allows_sequential_acquisition(self, tmp_path):
        from wafer.utils.process_lock import file_lock

        lock_path = str(tmp_path / "test.lock")
        with file_lock(lock_path):
            pass
        with file_lock(lock_path):
            pass


def test_acquire_timeout_constant():
    from wafer.utils.process_lock import _ACQUIRE_TIMEOUT

    assert _ACQUIRE_TIMEOUT > 0
    assert _ACQUIRE_TIMEOUT <= 120


class TestReadOwnerPid:
    def _patch_path(self, monkeypatch, lock_path):
        from wafer.utils import process_lock as process_lock_mod

        monkeypatch.setattr(process_lock_mod, "resolve_data_path", lambda _: str(lock_path))
        return process_lock_mod.SafeProcessLock

    def test_reads_pid_from_json(self, tmp_path, monkeypatch):
        lock_path = tmp_path / "waiter.lock"
        lock_path.write_text(json.dumps({"pid": 4321, "create_time": 1.0}), encoding="utf-8")
        lock_cls = self._patch_path(monkeypatch, lock_path)
        assert lock_cls.read_owner_pid("waiter") == 4321

    def test_reads_pid_from_plain_int(self, tmp_path, monkeypatch):
        lock_path = tmp_path / "waiter.lock"
        lock_path.write_text("777", encoding="utf-8")
        lock_cls = self._patch_path(monkeypatch, lock_path)
        assert lock_cls.read_owner_pid("waiter") == 777

    def test_returns_none_when_missing(self, tmp_path, monkeypatch):
        lock_cls = self._patch_path(monkeypatch, tmp_path / "absent.lock")
        assert lock_cls.read_owner_pid("absent") is None

    def test_returns_none_on_corrupt_content(self, tmp_path, monkeypatch):
        lock_path = tmp_path / "waiter.lock"
        lock_path.write_text("not json {", encoding="utf-8")
        lock_cls = self._patch_path(monkeypatch, lock_path)
        assert lock_cls.read_owner_pid("waiter") is None
