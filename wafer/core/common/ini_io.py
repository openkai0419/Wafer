from __future__ import annotations

import os
from configparser import ConfigParser


def write_ini(path: str, parser: ConfigParser) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = f"{path}.{os.getpid()}.tmp"
    try:
        with open(temp, "w", encoding="utf-8") as f:
            parser.write(f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    except OSError:
        if os.path.exists(temp):
            os.remove(temp)
        raise
