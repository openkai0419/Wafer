from pathlib import Path
import time
from typing import Optional, Union
from ..common.funcs import data_path

_PORT_FILE = Path(data_path("ipc_port.txt"))


def parse_port(port: Union[int, str]) -> int:
    """Return an integer port from a port number or address."""
    if isinstance(port, int):
        return port
    if isinstance(port, str):
        if port.startswith("tcp://"):
            return int(port.rsplit(":", 1)[-1])
        return int(port)
    raise ValueError(f"Invalid port: {port}")


def write_port(port: Union[int, str]) -> None:
    """Save broker port for other processes.

    Only the port number is stored; any address part is ignored.
    """
    _PORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    _PORT_FILE.write_text(str(parse_port(port)))


def read_port(timeout: float = 5.0) -> Optional[int]:
    """Read the saved broker port, waiting up to timeout seconds."""
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
