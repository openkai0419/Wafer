from pathlib import Path
import time
from typing import Optional, Union
from ..common.funcs import data_path

_PORT_FILE = Path(data_path("ipc_port.txt"))


def write_port(port: Union[int, str]) -> None:
    """Save broker address for other processes.

    Accepts either a bare port number or a full ZeroMQ address.
    """
    _PORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(port, int) or (isinstance(port, str) and port.isdigit()):
        addr = f"tcp://localhost:{port}"
    else:
        addr = str(port)
    _PORT_FILE.write_text(addr)


def read_port(timeout: float = 5.0) -> Optional[str]:
    """Read the saved broker address, waiting up to timeout seconds."""
    end = time.time() + timeout
    while True:
        try:
            data = _PORT_FILE.read_text().strip()
            if data and not data.startswith("tcp://"):
                data = f"tcp://localhost:{data}"
            return data
        except Exception:
            if time.time() > end:
                return None
            time.sleep(0.1)
