import json
import py_compile

from afterimages.core.ipc.transport import read_broker_port, remove_broker_port, write_broker_port


def test_compile():
    py_compile.compile('afterimages/core/ipc/transport.py')


def test_write_and_read():
    write_broker_port(12345)
    from afterimages.core.ipc.transport import _PORT_FILE
    assert _PORT_FILE.exists()
    data = json.loads(_PORT_FILE.read_text())
    assert data['port'] == 12345
    assert read_broker_port(timeout=0.1) == 12345


def test_read_missing():
    assert read_broker_port(timeout=0.1) is None


def test_remove():
    write_broker_port(11111)
    from afterimages.core.ipc.transport import _PORT_FILE
    assert _PORT_FILE.exists()
    remove_broker_port()
    assert not _PORT_FILE.exists()


def test_remove_missing():
    remove_broker_port()
