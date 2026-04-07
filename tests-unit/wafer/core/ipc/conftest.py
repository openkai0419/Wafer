import pytest


@pytest.fixture(autouse=True)
def _isolate_broker_port(tmp_path, monkeypatch):
    port_file = tmp_path / "ipc" / "broker.json"
    monkeypatch.setattr("wafer.core.ipc.transport._PORT_FILE", port_file)
