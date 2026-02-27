import json
import py_compile
import tempfile
from pathlib import Path
from unittest.mock import patch

from source.zmq.transport import read_broker_port, remove_broker_port, write_broker_port


def test_compile():
    py_compile.compile('source/zmq/transport.py')


def test_write_and_read(tmp_path):
    port_file = tmp_path / 'ipc' / 'broker.json'
    with patch('source.zmq.transport._PORT_FILE', port_file):
        write_broker_port(12345)
        assert port_file.exists()
        data = json.loads(port_file.read_text())
        assert data['port'] == 12345
        assert read_broker_port(timeout=0.1) == 12345


def test_read_missing(tmp_path):
    port_file = tmp_path / 'ipc' / 'broker.json'
    with patch('source.zmq.transport._PORT_FILE', port_file):
        assert read_broker_port(timeout=0.1) is None


def test_remove(tmp_path):
    port_file = tmp_path / 'ipc' / 'broker.json'
    with patch('source.zmq.transport._PORT_FILE', port_file):
        write_broker_port(11111)
        assert port_file.exists()
        remove_broker_port()
        assert not port_file.exists()


def test_remove_missing(tmp_path):
    port_file = tmp_path / 'nonexistent' / 'broker.json'
    with patch('source.zmq.transport._PORT_FILE', port_file):
        remove_broker_port()
