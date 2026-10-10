import pytest


@pytest.fixture(autouse=True)
def _isolate_broker_port(tmp_path, monkeypatch):
    port_file = tmp_path / "ipc" / "broker.json"
    monkeypatch.setattr("wafer.core.ipc.transport._PORT_FILE", port_file)


@pytest.fixture
def flush_ipc():
    def flush(*nodes):
        for node in nodes:
            assert node.request("mgmt.get_count", timeout=3.0) is not None

    return flush
