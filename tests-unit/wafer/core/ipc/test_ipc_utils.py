import json
from queue import Queue
from unittest.mock import patch

from wafer.core.ipc.transport import read_broker_port, remove_broker_port, write_broker_port, try_put


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
