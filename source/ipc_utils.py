from pathlib import Path
import time
from .common import data_path

_PORT_FILE = Path(data_path("ipc_port.txt"))


def write_port(port: int):
    """Save the port number for other processes"""
    _PORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PORT_FILE.write_text(str(port))


def read_port(timeout: float = 5.0) -> int | None:
    """Read the saved port number, waiting up to timeout seconds"""
    end = time.time() + timeout
    while True:
        try:
            return int(_PORT_FILE.read_text().strip())
        except Exception:
            if time.time() > end:
                return None
            time.sleep(0.1)
