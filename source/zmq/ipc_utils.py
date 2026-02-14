import json
import time
from pathlib import Path
from ..common.funcs import data_path

_PORT_FILE = Path(data_path('ipc/broker.json'))


def write_broker_port(port: int):
    _PORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PORT_FILE.write_text(json.dumps({'port': port}))


def read_broker_port(timeout: float = 5.0) -> int | None:
    end = time.time() + timeout
    while True:
        try:
            data = json.loads(_PORT_FILE.read_text())
            return int(data['port'])
        except Exception:
            if time.time() > end:
                return None
            time.sleep(0.1)


def remove_broker_port():
    try:
        _PORT_FILE.unlink(missing_ok=True)
    except Exception:
        pass
