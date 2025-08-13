import time
from pathlib import Path
from ..common.funcs import data_path
_PORT_FILE = Path(data_path('ipc_port.txt'))

def parse_port(port):
    if isinstance(port, int):
        return port
    if isinstance(port, str):
        if port.startswith('tcp://'):
            return int(port.rsplit(':', 1)[-1])
        return int(port)
    raise ValueError(f'Invalid port: {port}')

def write_port(port):
    _PORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PORT_FILE.write_text(str(parse_port(port)))

def read_port(timeout=5.0):
    end = time.time() + timeout
    while True:
        try:
            data = _PORT_FILE.read_text().strip()
            if data:
                return int(data)
            return None
        except Exception:
            if time.time() > end:
                return None
            time.sleep(0.1)
