from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import win32file


@contextmanager
def held_exclusively(path) -> Iterator[None]:
    handle = win32file.CreateFile(str(path), win32file.GENERIC_READ, 0, None, win32file.OPEN_EXISTING, 0, None)
    try:
        yield
    finally:
        handle.Close()
