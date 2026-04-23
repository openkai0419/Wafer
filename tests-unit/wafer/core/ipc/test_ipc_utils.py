import json
import py_compile
from queue import Queue
from unittest.mock import patch

from wafer.core.ipc.transport import read_broker_port, remove_broker_port, write_broker_port, try_put


def test_compile():
    py_compile.compile("wafer/core/ipc/transport.py")


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


def test_try_put_eviction_uses_stdlib_logging():
    q = Queue(maxsize=1)
    q.put_nowait("first")
    with patch("logging.getLogger") as mock_get_logger:
        mock_logger = mock_get_logger.return_value
        try_put(q, "second", label="test.evict")
        mock_get_logger.assert_called_once_with("AppLog")
        mock_logger.debug.assert_called_once()
        assert "test.evict" in mock_logger.debug.call_args[0][0]


def test_try_put_no_eviction_no_log():
    q = Queue(maxsize=2)
    with patch("logging.getLogger") as mock_get_logger:
        try_put(q, "item", label="test")
        mock_get_logger.assert_not_called()
