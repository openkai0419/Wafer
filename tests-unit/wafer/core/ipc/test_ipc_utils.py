import json
import threading
from pathlib import Path
from queue import Queue
from unittest.mock import patch

import pytest

from wafer.core.ipc.transport import port_file_stamp, read_broker_port, remove_broker_port, write_broker_port, try_put
from wafer.core.logs import AppLogger


def test_write_and_read():
    write_broker_port(12345)
    from wafer.core.ipc.transport import _PORT_FILE

    assert _PORT_FILE.exists()
    data = json.loads(_PORT_FILE.read_text())
    assert data["port"] == 12345
    assert read_broker_port(timeout=0.1) == 12345


def test_read_missing():
    assert read_broker_port(timeout=0.1) is None


def test_remove():
    write_broker_port(11111)
    from wafer.core.ipc.transport import _PORT_FILE

    assert _PORT_FILE.exists()
    remove_broker_port()
    assert not _PORT_FILE.exists()


def test_remove_missing():
    remove_broker_port()


def test_try_put_eviction_uses_non_recursive_log():
    q = Queue(maxsize=1)
    q.put_nowait("first")
    with patch("wafer.core.ipc.transport.debug_non_recursive") as log:
        try_put(q, "second", label="test.evict")
        log.assert_called_once()
        assert "test.evict" in log.call_args[0][0]


def test_try_put_no_eviction_no_log():
    q = Queue(maxsize=2)
    with patch("wafer.core.ipc.transport.debug_non_recursive") as log:
        try_put(q, "item", label="test")
        log.assert_not_called()


def test_read_retries_while_the_file_is_being_replaced(monkeypatch):
    write_broker_port(23456)
    from pathlib import Path

    real_read_text = Path.read_text
    failures = iter([PermissionError("locked"), PermissionError("locked")])

    def read_text(self, *args, **kwargs):
        error = next(failures, None)
        if error is not None:
            raise error
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)
    assert read_broker_port(timeout=1.0) == 23456


def test_write_retries_while_a_reader_holds_the_file(monkeypatch):
    from pathlib import Path

    from wafer.core.ipc import transport

    monkeypatch.setattr(transport, "PORT_FILE_REPLACE_RETRY_SEC", 0)
    real_replace = Path.replace
    failures = iter([PermissionError("in use"), PermissionError("in use")])

    def replace(self, target):
        error = next(failures, None)
        if error is not None:
            raise error
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", replace)
    write_broker_port(34567)
    assert json.loads(transport._PORT_FILE.read_text())["port"] == 34567


def deny_reads_of(monkeypatch, target, denied):
    real_read_text, real_read_bytes, real_stat = Path.read_text, Path.read_bytes, Path.stat

    def guard(real):
        def read(self, *args, **kwargs):
            if denied.is_set() and self == target:
                raise PermissionError(13, "Access is denied", str(self))
            return real(self, *args, **kwargs)

        return read

    monkeypatch.setattr(Path, "read_text", guard(real_read_text))
    monkeypatch.setattr(Path, "read_bytes", guard(real_read_bytes))
    monkeypatch.setattr(Path, "stat", guard(real_stat))


def test_readers_treat_a_denied_port_file_as_not_available_yet(monkeypatch):
    from wafer.core.ipc.transport import _PORT_FILE

    write_broker_port(12345)
    denied = threading.Event()
    denied.set()
    deny_reads_of(monkeypatch, _PORT_FILE, denied)
    logged = []
    monkeypatch.setattr(AppLogger, "info", lambda text: logged.append(text))
    monkeypatch.setattr(AppLogger, "debug", lambda text: logged.append(text))

    for _ in range(3):
        assert port_file_stamp(_PORT_FILE) is None
        assert read_broker_port(timeout=0.15) is None
    assert len([text for text in logged if str(_PORT_FILE) in text]) == 1

    denied.clear()
    assert read_broker_port(timeout=0.1) == 12345
    assert port_file_stamp(_PORT_FILE) is not None


def test_write_retries_a_replace_that_another_process_blocks(monkeypatch):
    from wafer.core.ipc.transport import _PORT_FILE

    real_replace = Path.replace
    attempts = []

    def flaky_replace(self, target):
        attempts.append(self)
        if len(attempts) < 3:
            raise PermissionError(13, "Access is denied", str(target))
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", flaky_replace)

    write_broker_port(23456)

    assert len(attempts) == 3
    assert json.loads(_PORT_FILE.read_text())["port"] == 23456


def test_write_raises_once_every_retry_is_blocked(monkeypatch):
    from wafer.core.ipc import transport

    monkeypatch.setattr(transport, "PORT_FILE_REPLACE_RETRY_SEC", 0)
    attempts = []

    def blocked_replace(self, target):
        attempts.append(self)
        raise PermissionError(13, "Access is denied", str(target))

    monkeypatch.setattr(Path, "replace", blocked_replace)

    with pytest.raises(PermissionError):
        write_broker_port(34567)
    assert len(attempts) == transport.PORT_FILE_REPLACE_RETRIES + 1
