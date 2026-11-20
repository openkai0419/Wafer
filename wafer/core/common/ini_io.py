from __future__ import annotations

import io
from configparser import ConfigParser

from .atomic_file import write_text_atomic


def write_ini(path: str, parser: ConfigParser) -> None:
    buffer = io.StringIO()
    parser.write(buffer)
    write_text_atomic(path, buffer.getvalue())
