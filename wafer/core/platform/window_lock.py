import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from time import sleep
from typing import TypeVar

from ..logs import AppLogger

LOCK_OFFSET = 1024
OWNER_READ_SIZE = LOCK_OFFSET
CLAIM_RETRIES = 5
CLAIM_RETRY_INTERVAL = 0.05

LockT = TypeVar("LockT", bound="WindowLock")


@dataclass(frozen=True)
class WindowOwner:
    pid: int
    hwnd: int


def lock_byte(fd: int) -> None:
    os.lseek(fd, LOCK_OFFSET, os.SEEK_SET)
    if sys.platform == "win32":
        import msvcrt

        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB, 1, LOCK_OFFSET)


def unlock_byte(fd: int) -> None:
    os.lseek(fd, LOCK_OFFSET, os.SEEK_SET)
    if sys.platform == "win32":
        import msvcrt

        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.lockf(fd, fcntl.LOCK_UN, 1, LOCK_OFFSET)


class WindowLock:
    held_paths: set[str] = set()

    def __init__(self, path: str, fd: int):
        self.path = path
        self.fd: int | None = fd

    @classmethod
    def acquire_path(cls: type[LockT], path: str) -> LockT | None:
        if path in WindowLock.held_paths:
            return None
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_BINARY", 0))
        try:
            lock_byte(fd)
        except OSError:
            os.close(fd)
            return None
        os.ftruncate(fd, 0)
        WindowLock.held_paths.add(path)
        return cls(path, fd)

    def set_window(self, hwnd: int) -> None:
        if self.fd is None:
            return
        payload = json.dumps({"pid": os.getpid(), "hwnd": hwnd}).encode()
        os.lseek(self.fd, 0, os.SEEK_SET)
        os.ftruncate(self.fd, 0)
        os.write(self.fd, payload)

    def release(self) -> None:
        fd, self.fd = self.fd, None
        if fd is None:
            return
        WindowLock.held_paths.discard(self.path)
        try:
            os.ftruncate(fd, 0)
            unlock_byte(fd)
        except OSError as exc:
            AppLogger.warning(f"WindowLock.release failed: {self.path}", exc=exc)
        finally:
            os.close(fd)

    @staticmethod
    def read_owner_at(path: str) -> WindowOwner | None:
        try:
            with open(path, "rb", buffering=0) as f:
                content = f.read(OWNER_READ_SIZE)
        except OSError:
            return None
        if not content:
            return None
        try:
            data = json.loads(content)
        except ValueError:
            return None
        if not isinstance(data, dict):
            return None
        pid, hwnd = data.get("pid"), data.get("hwnd")
        if not isinstance(pid, int) or not isinstance(hwnd, int):
            return None
        return WindowOwner(pid=pid, hwnd=hwnd)


def claim_window(acquire: Callable[[], LockT | None], activate_owner: Callable[[], bool]) -> LockT | None:
    for attempt in range(CLAIM_RETRIES + 1):
        lock = acquire()
        if lock is not None:
            return lock
        if activate_owner() or attempt == CLAIM_RETRIES:
            return None
        sleep(CLAIM_RETRY_INTERVAL)
    return None
