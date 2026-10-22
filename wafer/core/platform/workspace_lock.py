import json
import os
import sys
from collections.abc import Iterable
from dataclasses import dataclass

from ..common.paths import resolve_temp_path
from ..logs import AppLogger

LOCK_OFFSET = 1024
OWNER_READ_SIZE = LOCK_OFFSET


@dataclass(frozen=True)
class WorkspaceOwner:
    pid: int
    hwnd: int


def lock_path(slot_id: str) -> str:
    return os.path.join(resolve_temp_path("workspaces"), f"{slot_id}.lock")


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


class WorkspaceLock:
    held_slot_ids: set[str] = set()

    def __init__(self, slot_id: str, fd: int):
        self.slot_id = slot_id
        self.fd: int | None = fd

    @classmethod
    def acquire(cls, slot_id: str) -> "WorkspaceLock | None":
        if slot_id in cls.held_slot_ids:
            return None
        path = lock_path(slot_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_BINARY", 0))
        try:
            lock_byte(fd)
        except OSError:
            os.close(fd)
            return None
        os.ftruncate(fd, 0)
        cls.held_slot_ids.add(slot_id)
        return cls(slot_id, fd)

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
        WorkspaceLock.held_slot_ids.discard(self.slot_id)
        try:
            os.ftruncate(fd, 0)
            unlock_byte(fd)
        except OSError as exc:
            AppLogger.warning(f"WorkspaceLock.release failed: {self.slot_id}", exc=exc)
        finally:
            os.close(fd)

    @staticmethod
    def read_owner(slot_id: str) -> WorkspaceOwner | None:
        try:
            with open(lock_path(slot_id), "rb", buffering=0) as f:
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
        return WorkspaceOwner(pid=pid, hwnd=hwnd)

    @staticmethod
    def delete_file_if_unused(slot_id: str) -> bool:
        path = lock_path(slot_id)
        if not os.path.exists(path):
            return False
        probe = WorkspaceLock.acquire(slot_id)
        if probe is None:
            AppLogger.info(f"WorkspaceLock: kept the lock file of open workspace {slot_id}")
            return False
        probe.release()
        try:
            os.remove(path)
        except OSError as exc:
            AppLogger.warning(f"WorkspaceLock: could not delete the lock file of workspace {slot_id}", exc=exc)
            return False
        return True

    @staticmethod
    def open_slot_ids(slot_ids: Iterable[str]) -> set[str]:
        held = set()
        for slot_id in slot_ids:
            probe = WorkspaceLock.acquire(slot_id)
            if probe is None:
                held.add(slot_id)
            else:
                probe.release()
        return held
